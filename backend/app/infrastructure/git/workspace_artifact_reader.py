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

    **Which checkout.** Recovery keys a checkout by revision, so the directory
    name is not the repository's identity and the path cannot be concatenated.
    The tree is resolved through the metadata ingestion wrote - see
    `WorkspaceCheckouts` - using both the repository and the release, because
    reading a release's configuration out of another release's tree would
    quote a line that is not in the file being judged.
"""

from pathlib import Path

from app.infrastructure.workspace.checkouts import WorkspaceCheckouts


class ArtifactUnavailableError(RuntimeError):
    """The requested repository artifact cannot be read."""


class WorkspaceArtifactReader:
    """Reads repository files from the ingestion workspace."""

    def __init__(self, workspace_root: Path, checkout_subdirectory: str = "") -> None:
        """Bind the reader to the workspace, and to where a checkout sits in it.

        `checkout_subdirectory` is the path from a repository's own directory
        down to its working tree. Ingestion keeps the tree one level down,
        beside the files it writes about the tree, and that layout is the
        caller's knowledge rather than this reader's - which is why it is a
        parameter and not a constant here.
        """

        self._root = Path(workspace_root)
        self._checkouts = WorkspaceCheckouts(self._root, checkout_subdirectory)

    def read_text(self, repository_id: str, release_id: str, path: str) -> str:
        """Return the file's contents as the named release left it.

        `repository_id` may be the clone's id or the repository's own key;
        `release_id` selects which of the repository's checkouts to read.
        """

        target = self._resolve(repository_id, release_id, path)
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

        root = self._repository_root(repository_id, release_id)
        return sorted(
            str(match.relative_to(root)).replace("\\", "/")
            for match in root.glob(pattern)
            if match.is_file()
        )

    def _repository_root(self, repository_id: str, release_id: str) -> Path:
        root = self._checkouts.find(repository_id, release_id)
        if root is None:
            raise ArtifactUnavailableError(
                f"No workspace checkout for '{repository_id}' at '{release_id}'. "
                "Ingest it first."
            )
        return root

    def _resolve(self, repository_id: str, release_id: str, path: str) -> Path:
        """Resolve a repository-relative path, refusing to leave the checkout.

        A path from an inventory is data, and a manifest path containing '..'
        or a symlinked entry would otherwise read a file outside the
        repository. Checked here rather than trusted, because this reader is
        handed paths that came from a cloned third-party repository.
        """

        root = self._repository_root(repository_id, release_id).resolve()
        target = (root / path).resolve()
        if root != target and root not in target.parents:
            raise ArtifactUnavailableError(
                f"'{path}' resolves outside the checkout of '{repository_id}'."
            )
        return target
