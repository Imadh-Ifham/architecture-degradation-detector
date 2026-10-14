"""Workspace artifact reader.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Reads files out of a repository that ingestion has cloned into the local
    workspace.

    Kept as a separate module in this package rather than added to the git
    client: the client runs git commands, and this reads a working tree that
    git already produced. They fail for different reasons.

    The workspace is temporary and ingestion removes repositories from it
    again, so a repository that is not there is a normal situation rather than
    a bug. It raises, naming what is missing, because an empty read would look
    exactly like a repository that genuinely declares nothing - and validation
    would then report a clean architecture instead of an unavailable one.
"""

from pathlib import Path


class ArtifactUnavailableError(RuntimeError):
    """The requested repository artifact cannot be read."""


class WorkspaceArtifactReader:
    """Reads repository files from the ingestion workspace."""

    def __init__(self, workspace_root: Path) -> None:
        self._root = Path(workspace_root)

    def read_text(self, repository_id: str, release_id: str, path: str) -> str:
        """Return the file's contents.

        `release_id` is accepted and not used to locate the file: the workspace
        holds one checkout per repository, and which release that checkout
        represents is the caller's knowledge. It stays in the signature because
        the port is written for a reader that can serve several releases, and a
        later implementation reading from git history will need it.
        """

        target = self._resolve(repository_id, path)
        try:
            return target.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise ArtifactUnavailableError(
                f"'{path}' is not in the workspace checkout of '{repository_id}'. "
                "The clone may have been removed; re-ingest the repository."
            ) from error
        except UnicodeDecodeError as error:
            raise ArtifactUnavailableError(
                f"'{path}' in '{repository_id}' is not UTF-8 text."
            ) from error

    def list_paths(self, repository_id: str, release_id: str, pattern: str) -> list[str]:
        """Return every repository-relative path matching `pattern`, sorted."""

        root = self._repository_root(repository_id)
        return sorted(
            str(match.relative_to(root)).replace("\\", "/")
            for match in root.glob(pattern)
            if match.is_file()
        )

    def _repository_root(self, repository_id: str) -> Path:
        root = self._root / repository_id
        if not root.is_dir():
            raise ArtifactUnavailableError(
                f"No workspace checkout for '{repository_id}'. Ingest it first."
            )
        return root

    def _resolve(self, repository_id: str, path: str) -> Path:
        """Resolve a repository-relative path, refusing to leave the checkout.

        A path from an inventory is data, and a manifest path containing '..'
        or a symlinked entry would otherwise read a file outside the
        repository. Checked here rather than trusted, because this reader is
        handed paths that came from a cloned third-party repository.
        """

        root = self._repository_root(repository_id).resolve()
        target = (root / path).resolve()
        if root != target and root not in target.parents:
            raise ArtifactUnavailableError(
                f"'{path}' resolves outside the checkout of '{repository_id}'."
            )
        return target
