"""Graph construction ports.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    The one dependency this component has on the outside world: the historical
    graph store.

    The store is the source of truth for architecture history. The JSON report
    written beside the analysis is a report, not a second database, and nothing
    downstream is meant to read history out of it.
"""

from collections.abc import Sequence
from typing import Protocol

from app.domain.architecture_snapshot import (
    ArchitectureSnapshot,
    SnapshotSummary,
)


class ArchitectureSnapshotStore(Protocol):
    """Persists and reads version-scoped architecture snapshots.

    **Idempotency.** `publish` is idempotent on `snapshot.snapshot_id`: a
    rerun replaces that snapshot's own elements and relationships and touches
    no other snapshot. It must never delete a snapshot merely because a newer
    release is being analyzed, and never touch a different repository.

    **Isolation.** Every read is scoped by `repository_id`. Two repositories
    that share a release tag and a component name stay separate histories.

    **Removal only removes.** `delete_snapshot` and `delete_repository` exist
    because a clone that is deleted from the machine must not leave its graph
    behind - history nobody can reach is a leak, not a record. Neither method
    may touch another repository, and neither may touch the validated graph
    that a different component owns.
    """

    def publish(self, snapshot: ArchitectureSnapshot) -> str:
        """Persist the snapshot and return a reference to it."""
        ...

    def read(
        self, repository_id: str, snapshot_id: str
    ) -> ArchitectureSnapshot | None:
        """Return one snapshot, or `None` when it is not stored."""
        ...

    def history(self, repository_id: str) -> Sequence[SnapshotSummary]:
        """Return every snapshot of a repository, oldest first."""
        ...

    def delete_snapshot(self, repository_id: str, snapshot_id: str) -> bool:
        """Delete one snapshot and the elements it owns.

        Returns whether a snapshot was there to delete.
        """
        ...

    def delete_repository(self, repository_id: str) -> int:
        """Delete every snapshot of a repository.

        Returns how many snapshots were removed.
        """
        ...


__all__ = ["ArchitectureSnapshotStore"]
