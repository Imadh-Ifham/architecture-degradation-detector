"""Gateway to the architecture recovery component.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    Reads the architecture recovery component's output - from its graph, from a
    recorded snapshot, or from its inventory document - and translates it into
    the shape the validation component consumes.

    ---------------------------------------------------------------------
    WHY A GATEWAY, AND WHY IT IS IN `infrastructure/`
    ---------------------------------------------------------------------

    Recovery is an **external system** as far as validation is concerned. The
    component diagram (`Figure_4.2_C2_Component_Diagram`) gives it the
    `<<external_system>>` stereotype - the same one it gives the ADR Git
    repository, the hosted model API and the degradation detection component.
    `ARCHITECTURE.md` §2 makes this layer responsible for "technical adapters
    to the outside world", and an adapter to an external system is exactly
    that. It sits beside `ai/`, which adapts another external system, for the
    same reason.

    It is named for **what it talks to**, not for what it carries. Every
    sibling here - `postgres/`, `neo4j/`, `git/`, `ai/` - is named after the
    thing on the far side of it. This package used to be called
    `recovered_architecture/`, which named the artifact instead, and that
    created two problems: it read like a domain model filed in the wrong
    layer, and it collided with `app/domain/recovered_architecture.py`, where
    the actual domain shape lives. One name, two layers, two different things.
    `recovery_gateway` says adapter, so the reader never has to wonder.

    ---------------------------------------------------------------------
    WHY THE TRANSLATION LIVES HERE AND NOT INSIDE THE COMPONENT
    ---------------------------------------------------------------------

    This is forced by the direction of dependency, not chosen by convention.

    The port is `read(repository_id, release_id) -> RecoveredArchitecture`: it
    returns a domain object. Whatever satisfies it opens a file or queries a
    graph database, so it has to live out here - the validation component may
    not import a driver, and its own structural tests forbid it importing this
    layer at all.

    Moving `translation.py` into the component would therefore mean a reader
    out here importing a module in there, which inverts the layering:
    infrastructure is the outer ring and components the inner one, and the
    rule that components never import infrastructure only means something
    while nothing points the other way.

    The remaining alternative - have the port return a raw `dict` and let the
    component translate - is worse for a specific reason. It puts recovery's
    field names inside the validation component, which is precisely the churn
    this package exists to absorb, and it leaves the boundary untyped. Every
    rename on recovery's side would then reach into the component.

    So: everything that knows recovery's shape is in here, and the component
    sees only its own domain model, through a protocol.

    ---------------------------------------------------------------------
    WHAT IS IN HERE
    ---------------------------------------------------------------------

    `workspace.py`              recovery's ingestion records: both ids, the
                                release tag, the commit and the release date
    `graph_translation.py`      recovery's architecture graph, in this
                                component's vocabulary
    `graph_store_reader.py`     reads recovery's graph store - the live input
    `inventory_schema.py`       recovery's inventory shape, and CONTRACT_VERSION
    `translation.py`            the only module that knows its field names
    `inventory_file_reader.py`  reads recovery's live inventory document
    `snapshot_schema.py`        the recorded snapshot's shape, in Pydantic
    `snapshot_file_reader.py`   reads a recorded snapshot - the rehearsed input
    `fixture_reader.py`         reads a committed inventory recording

    ---------------------------------------------------------------------
    WHAT THE GRAPH READER REPLACED
    ---------------------------------------------------------------------

    Until 2026-10-19 recovery reported relationships between files and
    components rather than between one element and another, and a module in
    here derived the missing ones from deployment manifests. Recovery now
    publishes its own, from configured endpoints and from source-level calls,
    so the stand-in is gone.

    Nothing inside the validation component changed when it went, which is the
    answer to whether the port was drawn in the right place.
"""

from .fixture_reader import FixtureArchitectureReader
from .graph_store_reader import (
    ArchitectureGraphStore,
    GraphContractError,
    GraphStoreReader,
)
from .graph_translation import (
    incompleteness_note,
    released_at,
    translate_snapshot,
    unresolved_warnings,
)
from .inventory_file_reader import InventoryFileArchitectureReader
from .inventory_schema import (
    CONTRACT_VERSION,
    InventoryContractError,
    InventoryFieldError,
    InventoryVersionError,
)
from .snapshot_file_reader import SnapshotFileReader
from .snapshot_schema import (
    SNAPSHOT_SCHEMA_VERSION,
    SnapshotContractError,
    SnapshotFieldError,
    SnapshotVersionError,
    parse_snapshot,
)
from .workspace import WorkspaceIndex, WorkspaceUnavailable

__all__ = [
    "CONTRACT_VERSION",
    "SNAPSHOT_SCHEMA_VERSION",
    "ArchitectureGraphStore",
    "FixtureArchitectureReader",
    "GraphContractError",
    "GraphStoreReader",
    "InventoryContractError",
    "InventoryFieldError",
    "InventoryFileArchitectureReader",
    "InventoryVersionError",
    "SnapshotContractError",
    "SnapshotFieldError",
    "SnapshotFileReader",
    "SnapshotVersionError",
    "WorkspaceIndex",
    "WorkspaceUnavailable",
    "incompleteness_note",
    "parse_snapshot",
    "released_at",
    "translate_snapshot",
    "unresolved_warnings",
]
