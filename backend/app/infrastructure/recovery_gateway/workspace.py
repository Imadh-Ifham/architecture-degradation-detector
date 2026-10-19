"""Ingestion workspace index.

Author: Aman Mohamed M.A
Date: 2026-10-19
Description:
    Finds the ingestion record behind a repository id, so nothing downstream
    has to derive, guess or be told what recovery already wrote down.

    Recovery keeps two identifiers and they are not interchangeable. The
    **workspace id** names one clone of one revision, and it is the directory
    the inventory and the working tree sit in. The **repository key** names the
    repository itself, is the same for every release of it, and is what the
    architecture graph is stored under. A release ingest creates a second
    workspace with a second id and the same key.

    A reader that knew only one of them could reach only half of recovery's
    output, so this resolves both from the `metadata.json` recovery writes
    beside every clone - which also carries the release tag, the commit, and
    the date the release was cut.

    Nothing here parses a url or rebuilds an identifier. Deriving the key a
    second time would be a second implementation of recovery's rule, and the
    two would disagree the first time it changed.
"""

import json
from pathlib import Path

from app.domain.repository import IngestedRepository

METADATA_FILE_NAME = "metadata.json"


class WorkspaceUnavailable(LookupError):
    """No ingested revision answers to that repository and release.

    Carries what the workspace does hold. A caller who asked for the wrong
    release and a caller who asked before ingesting get the same bare failure
    otherwise, and they need different things done about them.
    """

    def __init__(self, repository_id: str, release_id: str | None, known) -> None:
        wanted = repository_id if release_id is None else f"{repository_id} @ {release_id}"
        listed = ", ".join(known) if known else "nothing is ingested"
        super().__init__(
            f"No ingested revision for '{wanted}'. The workspace holds: {listed}."
        )
        self.repository_id = repository_id
        self.release_id = release_id


class WorkspaceIndex:
    """Reads recovery's ingestion records out of the workspace."""

    def __init__(self, repositories_root: Path) -> None:
        self._root = Path(repositories_root)

    def records(self) -> tuple[IngestedRepository, ...]:
        """Every ingested revision currently on this machine, newest first."""

        if not self._root.is_dir():
            return ()

        found = []

        for entry in sorted(self._root.iterdir()):
            record = self._record_in(entry)
            if record is not None:
                found.append(record)

        return tuple(sorted(found, key=lambda item: item.ingested_at, reverse=True))

    def resolve(
        self, repository_id: str, release_id: str | None = None
    ) -> IngestedRepository:
        """Return the ingested revision a caller means.

        `repository_id` may be either identifier. Callers hold whichever one
        the route they came through handed them, and asking them to know which
        is asking them to know about recovery's directory layout.

        When two revisions match - the same release ingested twice - the most
        recently ingested wins, because the older clone may no longer be on
        disk at the commit it claims.
        """

        matches = [
            record
            for record in self.records()
            if repository_id in (record.id, record.repository_key)
            and (release_id is None or release_id in (record.release_id, record.release_tag))
        ]

        if not matches:
            raise WorkspaceUnavailable(repository_id, release_id, self._describe())

        return matches[0]

    def find(
        self, repository_id: str, release_id: str | None = None
    ) -> IngestedRepository | None:
        """The ingested revision, or nothing when it is not on this machine.

        A clone can be removed while the architecture recovery stored for it
        stays in the graph. The architecture is still readable and still
        true; what is gone is the working tree, and only the parts of a
        screen that quote a file need that. So a caller that can do without
        the tree asks here, and one that cannot asks `resolve`.
        """

        try:
            return self.resolve(repository_id, release_id)
        except WorkspaceUnavailable:
            return None

    def _describe(self) -> tuple[str, ...]:
        return tuple(
            f"{record.repository_key} @ {record.release_id}"
            for record in self.records()
        )

    def _record_in(self, directory: Path) -> IngestedRepository | None:
        """Read one workspace's record, or nothing when it holds none.

        A directory without a readable record is skipped rather than raised
        on: a half-written clone or something else entirely under the root
        must not stop a caller finding the repository they asked for.
        """

        metadata = directory / METADATA_FILE_NAME

        if not metadata.is_file():
            return None

        try:
            return IngestedRepository.from_metadata(
                json.loads(metadata.read_text(encoding="utf-8")), directory
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            return None


__all__ = ["METADATA_FILE_NAME", "WorkspaceIndex", "WorkspaceUnavailable"]
