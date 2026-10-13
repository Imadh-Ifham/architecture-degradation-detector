"""Repository ingestion service.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Clones repositories into a temporary workspace on the machine and removes
    them again. Each repository gets its own directory holding the working
    tree plus a metadata record, so removing it is a single directory delete.
"""

import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.components.architecture_recovery.repository_ingestion.errors import (
    RepositoryNotFound,
)
from app.components.architecture_recovery.repository_ingestion.validation import (
    is_valid_repository_id,
    redact_credentials,
    validate_branch,
    validate_url,
)
from app.domain.repository import IngestedRepository
from app.infrastructure.git.client import GitClient


METADATA_FILE_NAME = "metadata.json"
SOURCE_DIRECTORY_NAME = "source"
STAGING_DIRECTORY_NAME = ".staging"


class RepositoryIngestionService:
    """Clones repositories into a temporary workspace and removes them again.

    Each ingested repository lives in its own directory below the workspace
    root, holding the working tree (`source/`) plus a `metadata.json` record.
    Re-ingesting the same url and branch replaces the existing clone, so the
    operation is idempotent and always reflects the current branch tip.
    """

    def __init__(self, git_client: GitClient, root: Path) -> None:
        """Bind the service to a git client and a workspace root."""

        self._git = git_client
        self._root = Path(root)

    def ingest(self, url: str, branch: str) -> IngestedRepository:
        """Clone `url` at `branch` into the workspace and return its record.

        Raises `InvalidRepositorySource` for a rejected source, and
        `GitCommandError` when git itself fails.
        """

        # Redact first, so credentials can never reach disk or the response.
        source_url = redact_credentials(validate_url(url))
        source_branch = validate_branch(branch)

        repository_id = build_repository_id(source_url, source_branch)
        target = self._repository_directory(repository_id)
        staging = self._root / STAGING_DIRECTORY_NAME / uuid.uuid4().hex

        try:
            clone_path = staging / SOURCE_DIRECTORY_NAME
            self._git.clone(source_url, source_branch, clone_path)

            record = IngestedRepository(
                id=repository_id,
                url=source_url,
                branch=source_branch,
                commit=self._git.head_commit(clone_path),
                path=target / SOURCE_DIRECTORY_NAME,
                ingested_at=datetime.now(timezone.utc),
            )

            (staging / METADATA_FILE_NAME).write_text(
                json.dumps(record.to_metadata(), indent=2),
                encoding="utf-8",
            )

            # Clone into a per-attempt staging directory first, then swap it in.
            # `os.replace` is an atomic rename within one filesystem, so the
            # target is never observed half-written and a failed clone leaves
            # any previous clone untouched.
            if target.exists():
                _remove_tree(target)

            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, target)

            return record
        finally:
            # Discard staging leftovers, including a partially written clone.
            # After a successful swap the directory no longer exists.
            _discard_tree(staging)

    def list_ingested(self) -> list[IngestedRepository]:
        """Return every repository currently held in the workspace.

        Dot-directories (such as the staging area) and directories without a
        metadata file are skipped.
        """

        if not self._root.is_dir():
            return []

        repositories = []
        for entry in sorted(self._root.iterdir()):
            if entry.name.startswith(".") or not entry.is_dir():
                continue

            metadata_path = entry / METADATA_FILE_NAME
            if not metadata_path.is_file():
                continue

            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            repositories.append(
                IngestedRepository.from_metadata(
                    metadata,
                    entry / SOURCE_DIRECTORY_NAME,
                )
            )

        return repositories

    def remove(self, repository_id: str) -> None:
        """Delete an ingested repository from the machine.

        Raises `RepositoryNotFound` when no such repository exists.
        """

        _remove_tree(self._existing_directory(repository_id))

    def _existing_directory(self, repository_id: str) -> Path:
        """Resolve an id to an existing workspace directory, or raise."""

        # An id that does not match our generated shape is treated as absent,
        # which also blocks traversal such as "../../etc" before any I/O.
        target = (
            self._repository_directory(repository_id)
            if is_valid_repository_id(repository_id)
            else None
        )

        if target is None or not target.is_dir():
            raise RepositoryNotFound(
                f"No ingested repository with id '{repository_id}'."
            )

        return target

    def _repository_directory(self, repository_id: str) -> Path:
        """Return the workspace directory that belongs to `repository_id`."""

        root = self._root.resolve()
        target = (root / repository_id).resolve()

        # Defence in depth: even with an already validated id, never operate
        # outside the workspace root (for example through a symlinked entry).
        if not target.is_relative_to(root):
            raise RepositoryNotFound(
                f"No ingested repository with id '{repository_id}'."
            )

        return target


def _remove_tree(path: Path) -> None:
    """Delete a directory tree, clearing the read-only bit git sets on Windows.

    `git clone` marks `.git/objects/pack/*` as read-only, and a plain
    `shutil.rmtree` fails on those with WinError 5.
    """

    def clear_read_only_bit(function, failing_path, _exception) -> None:
        # `onexc` supplies the failing callable, so clear the attribute and
        # retry that same operation on the same path.
        os.chmod(failing_path, stat.S_IWRITE)
        function(failing_path)

    shutil.rmtree(path, onexc=clear_read_only_bit)


def _discard_tree(path: Path) -> None:
    """Best-effort cleanup that never raises when the tree is already gone."""

    try:
        _remove_tree(path)
    except OSError:
        pass


def build_repository_id(url: str, branch: str) -> str:
    """Derive a stable, filesystem-safe id for a url and branch pair.

    The readable prefix makes the id recognisable; the hash suffix keeps two
    branches, or two repositories sharing a name, from colliding.
    """

    digest = hashlib.sha256(f"{url}@{branch}".encode("utf-8")).hexdigest()[:12]
    return f"{_slugify(url)}-{digest}"


def _slugify(url: str) -> str:
    """Reduce a url to its repository name, safe for use inside a path."""

    trimmed = url.rstrip("/")

    if trimmed.endswith(".git"):
        trimmed = trimmed[: -len(".git")]

    # Take the last path segment; the extra split also handles the scp-like
    # `host:path` form, where the name follows the colon.
    name = trimmed.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:40] or "repository"
