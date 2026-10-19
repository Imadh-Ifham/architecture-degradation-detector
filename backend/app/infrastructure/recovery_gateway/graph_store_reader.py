"""Architecture graph reader.

Author: Aman Mohamed M.A
Date: 2026-10-19
Description:
    Reads a release's architecture out of recovery's graph store, which is
    where recovery now keeps it.

    This is the live integration. The other readers in this package read a
    document on disk; this one asks the store recovery publishes to, and gets
    back the same release recovery analysed, with recovery's own edges.

    **It calls the store, never the database.** Recovery's store is already a
    protocol with a tested implementation, idempotent per snapshot and scoped
    per repository. Writing a second set of queries here would be a second
    thing to keep in step with recovery's labels, and it would drift on
    exactly the release somebody was looking at. The protocol is restated
    below rather than imported, so this package depends on the domain shape
    and on nothing inside another component.

    **Two identifiers, resolved rather than assumed.** A validation run names
    a release the way a person does - `v0.10.0` - while a snapshot is
    identified by a hash of the commit and recovery's analysis configuration.
    The store answers `history()` with both, so the release id is matched
    there and the snapshot id is read from the row rather than constructed.
    Where one release has been analysed twice, the newer analysis wins and the
    id it came from is recorded on the result.

    **Paths come from the inventory, because the graph has none.** Recovery's
    evidence carries record identifiers, not file paths, and evidence
    retrieval quotes lines out of files. So the graph supplies the
    architecture and the inventory supplies the paths, joined on the component
    id both documents use. Without it the manifests a decision is read from
    cannot be found, and nothing downstream could quote anything.
"""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol

from app.domain.architecture_snapshot import ArchitectureSnapshot, SnapshotSummary
from app.domain.recovered_architecture import RecoveredArchitecture
from app.domain.validated_architecture import ReleaseDateSource

from .graph_translation import (
    READER_NAME,
    incompleteness_note,
    released_at,
    translate_snapshot,
    unresolved_warnings,
)
from .inventory_file_reader import InventoryFileArchitectureReader
from .inventory_schema import InventoryContractError
from .workspace import WorkspaceIndex, WorkspaceUnavailable


class GraphContractError(ValueError):
    """Recovery's graph cannot answer for that repository and release.

    One error for every way this boundary fails, because a caller does the
    same thing about all of them: the message says what the store does hold,
    so the difference between a release that was never analysed and a
    repository that was never ingested is in the text rather than in the type.
    """


class ArchitectureGraphStore(Protocol):
    """Recovery's historical graph, as this reader uses it.

    Restated here rather than imported so that this package depends on the
    domain and on nothing inside another component. The structural match is
    what makes the real store satisfy it.
    """

    def read(
        self, repository_id: str, snapshot_id: str
    ) -> ArchitectureSnapshot | None: ...

    def history(self, repository_id: str) -> Sequence[SnapshotSummary]: ...


class GraphStoreReader:
    """Reads a recovered architecture from recovery's graph store."""

    def __init__(
        self,
        store: ArchitectureGraphStore,
        repositories_root: Path,
    ) -> None:
        self._store = store
        self._workspace = WorkspaceIndex(repositories_root)
        self._inventory = InventoryFileArchitectureReader(repositories_root)

    def read(self, repository_id: str, release_id: str) -> RecoveredArchitecture:
        """Return the architecture recovery stored for one release."""

        snapshot, workspace_id = self._snapshot(repository_id, release_id)
        paths, manifests = self._paths(workspace_id, release_id)

        return translate_snapshot(
            snapshot,
            repository_id=repository_id,
            release_id=release_id,
            source_reference=f"graph:{snapshot.snapshot_id}",
            source_paths=paths,
            manifest_paths=manifests,
            reader=READER_NAME,
        )

    def manifest_paths(self, repository_id: str) -> tuple[str, ...]:
        """Every manifest recovery classified, for the decision sources."""

        record = self._workspace.resolve(repository_id)
        return self._manifests(record.id)

    def released_at(
        self, repository_id: str, release_id: str
    ) -> tuple[datetime, ReleaseDateSource] | None:
        """When the release was cut, by recovery's account, or nothing.

        A consumer gates on this field, so recovery's answer is better than
        reading git a second time for a second opinion. Nothing is returned
        when recovery only had the timestamp of its own analysis - see
        `graph_translation.released_at`.
        """

        try:
            snapshot, _ = self._snapshot(repository_id, release_id)
        except (GraphContractError, WorkspaceUnavailable):
            return None

        return released_at(snapshot)

    def notes(self, repository_id: str, release_id: str) -> tuple[str, ...]:
        """What recovery said about this scan that a reviewer should see.

        An incomplete scan and an unresolved reference are both findings and
        neither is an error, so they are returned to be reported rather than
        raised.
        """

        snapshot, _ = self._snapshot(repository_id, release_id)
        note = incompleteness_note(snapshot)

        return ((note,) if note else ()) + unresolved_warnings(snapshot)

    # ------------------------------------------------------------------ #

    def _snapshot(
        self, repository_id: str, release_id: str
    ) -> tuple[ArchitectureSnapshot, str]:
        """The stored snapshot for one release, and the workspace behind it."""

        try:
            record = self._workspace.resolve(repository_id, release_id)
        except WorkspaceUnavailable as error:
            raise GraphContractError(str(error)) from error

        summary = self._summary(record.repository_key, release_id)
        snapshot = self._store.read(record.repository_key, summary.snapshot_id)

        if snapshot is None:
            # history() named it, so this is the store losing a snapshot
            # between two calls rather than a caller asking for the wrong one.
            raise GraphContractError(
                f"Recovery's history lists snapshot '{summary.snapshot_id}' for "
                f"release '{release_id}', and the store does not hold it."
            )

        return snapshot, record.id

    def _summary(self, repository_key: str, release_id: str) -> SnapshotSummary:
        """The newest analysis of one release.

        A snapshot is identified by the commit *and* recovery's analysis
        configuration, so re-analysing one release under changed settings
        leaves two. Taking the first match would validate whichever happened
        to be written first; taking the newest is at least a rule, and the one
        that was taken is recorded on the architecture's provenance.
        """

        history = self._store.history(repository_key)
        matching = [
            item
            for item in history
            if release_id in (item.release_id, item.release_tag)
        ]

        if not matching:
            listed = ", ".join(item.release_id for item in history) or "none"
            raise GraphContractError(
                f"Recovery has no architecture for release '{release_id}' of "
                f"'{repository_key}'. Analysed releases: {listed}."
            )

        return max(matching, key=lambda item: item.analysis_timestamp)

    def _paths(
        self, workspace_id: str, release_id: str
    ) -> tuple[dict[str, tuple[str, ...]], tuple[str, ...]]:
        """Source paths per element and the manifest list, from the inventory.

        Absent, the architecture is still returned. A missing inventory means
        nothing can be quoted later and that failure belongs where the quote
        is attempted, naming the file it wanted - not here, where it would
        read as recovery having no architecture at all.
        """

        try:
            inventory = self._inventory.read(workspace_id, release_id)
        except (InventoryContractError, OSError):
            return {}, ()

        paths = {
            element.id: element.source_paths
            for element in inventory.elements
            if element.source_paths
        }

        return paths, inventory.manifest_paths

    def _manifests(self, workspace_id: str) -> tuple[str, ...]:
        try:
            return self._inventory.manifest_paths(workspace_id)
        except (InventoryContractError, OSError):
            return ()


__all__ = ["ArchitectureGraphStore", "GraphContractError", "GraphStoreReader"]
