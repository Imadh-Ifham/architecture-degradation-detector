"""Graph construction subcomponent.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Assembles the recovered evidence into one version-scoped architecture
    snapshot per analyzed revision, writes its report, and publishes it to the
    historical graph store.

    Two rules define the stage. A newer release never overwrites an earlier
    snapshot: the snapshot id is derived from the repository, the resolved
    commit and the analysis configuration, and every write is scoped to that
    id. And a snapshot that could not be built completely says so, because a
    missing element in a failed scan is not a removed element.

    No degradation score is computed here. This stage stores accurate,
    versioned architecture data and the provenance needed to compare releases.
"""

from app.components.architecture_recovery.graph_construction.builder import (
    CONFIGURATION,
    CONFIGURATION_KEY,
    GENERATOR_NAME,
    GENERATOR_VERSION,
    SnapshotBuilder,
    order_timestamp_for,
    relationship_identity,
    snapshot_identity,
)
from app.components.architecture_recovery.graph_construction.errors import (
    GraphConstructionError,
    GraphConstructionInputError,
    GraphConstructionWriteError,
    SnapshotStoreError,
)
from app.components.architecture_recovery.graph_construction.inputs import (
    ComponentRecord,
    DependencyRecord,
    FindingRecord,
    SnapshotInputs,
    UnresolvedRecord,
    inputs_from_documents,
    inputs_from_reports,
)
from app.components.architecture_recovery.graph_construction.models import (
    REPORT_SCHEMA_VERSION,
    GraphConstructionReport,
    GraphConstructionSummary,
)
from app.components.architecture_recovery.graph_construction.ports import (
    ArchitectureSnapshotStore,
)
from app.components.architecture_recovery.graph_construction.schemas import (
    GraphConstructionSummaryResponse,
    SnapshotSummaryResponse,
)
from app.components.architecture_recovery.graph_construction.service import (
    GraphConstructionService,
    graph_construction_service_from_settings,
    new_analysis_run,
    release_from_ingested,
)
from app.components.architecture_recovery.graph_construction.writer import (
    GRAPH_CONSTRUCTION_DIRECTORY,
    GRAPH_CONSTRUCTION_FILE_NAME,
    load_graph_construction,
    snapshot_directory,
    write_graph_construction,
)

__all__ = [
    "CONFIGURATION",
    "CONFIGURATION_KEY",
    "GENERATOR_NAME",
    "GENERATOR_VERSION",
    "GRAPH_CONSTRUCTION_DIRECTORY",
    "GRAPH_CONSTRUCTION_FILE_NAME",
    "REPORT_SCHEMA_VERSION",
    "ArchitectureSnapshotStore",
    "ComponentRecord",
    "DependencyRecord",
    "FindingRecord",
    "GraphConstructionError",
    "GraphConstructionInputError",
    "GraphConstructionReport",
    "GraphConstructionService",
    "GraphConstructionSummary",
    "GraphConstructionSummaryResponse",
    "GraphConstructionWriteError",
    "SnapshotBuilder",
    "SnapshotInputs",
    "SnapshotStoreError",
    "SnapshotSummaryResponse",
    "UnresolvedRecord",
    "graph_construction_service_from_settings",
    "inputs_from_documents",
    "inputs_from_reports",
    "load_graph_construction",
    "new_analysis_run",
    "order_timestamp_for",
    "relationship_identity",
    "release_from_ingested",
    "snapshot_directory",
    "snapshot_identity",
    "write_graph_construction",
]
