"""Where in the workspace a release's working tree is.

Author: Imadh Ifham
Date: 2026-10-20
Description:
    Resolves a repository and a release to the checkout ingestion left behind.

    Recovery keys a checkout by *revision*, not by repository:
    `microservices-demo-<hash of url@v0.9.0>` is one release's tree and
    `microservices-demo-<hash of url>` is the repository both releases belong
    to. A reader handed either identifier therefore cannot build the path by
    concatenation - it has to resolve it through the `metadata.json` ingestion
    wrote, which is what this does.

    Two rules, in order:

      * **this release's checkout.** A tree at another commit is a different
        file, and quoting a line out of it would be worse than quoting none.
      * **when the repository has exactly one checkout**, that one - the case
        where a caller names a release the workspace does not name (a commit
        id rather than the tag it was ingested under).

    Two checkouts and no exact match is ambiguous, so it resolves to nothing
    rather than guessing: guessing would validate one release against another
    release's files and report the result as this one's.
"""

from pathlib import Path

from app.infrastructure.recovery_gateway.workspace import WorkspaceIndex


class WorkspaceCheckouts:
    """Finds the working tree for one repository and release."""

    def __init__(self, workspace_root: Path, checkout_subdirectory: str = "") -> None:
        """Bind the resolver to a workspace, and to where a tree sits in one.

        `checkout_subdirectory` is the path from a cloned repository's own
        directory down to its working tree. Ingestion keeps the tree one level
        down, beside the metadata it writes, and that layout is the caller's
        knowledge rather than this module's.
        """

        self._root = Path(workspace_root)
        self._checkout_subdirectory = checkout_subdirectory
        self._index = WorkspaceIndex(self._root)

    def find(self, repository_id: str, release_id: str | None = None) -> Path | None:
        """The checkout for that release, or `None` when there is not exactly one.

        `repository_id` may be either identifier recovery uses: the clone's
        workspace id, or the repository's own key. Callers hold whichever one
        the route they came through handed them.
        """

        directory = self._directory(repository_id, release_id)
        if directory is None:
            return None

        checkout = (
            directory / self._checkout_subdirectory
            if self._checkout_subdirectory
            else directory
        )

        return checkout if checkout.is_dir() else None

    def _directory(self, repository_id: str, release_id: str | None) -> Path | None:
        """The cloned repository's own directory, the one holding `source/`."""

        record = self._index.find(repository_id, release_id)

        if record is None:
            same_repository = [
                item
                for item in self._index.records()
                if repository_id in (item.id, item.repository_key)
            ]
            record = same_repository[0] if len(same_repository) == 1 else None

        if record is not None:
            # The workspace id names the clone's own directory - the one that
            # holds `source/` beside its `metadata.json`. Derived from the id
            # rather than from the record's `path`, because two readers of the
            # same record disagree about whether `path` is the clone or its
            # tree, and this module needs the directory.
            return self._root / record.id

        # A workspace laid out without metadata - a fixture, or a directory
        # written by hand - where the id is the directory name.
        return self._root / repository_id


__all__ = ["WorkspaceCheckouts"]
