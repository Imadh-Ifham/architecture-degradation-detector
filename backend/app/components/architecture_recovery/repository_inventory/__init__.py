"""Repository inventory subcomponent.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Inventories a repository working tree into a single versioned JSON document
    and re-exports the public surface of the subcomponent.

    Pipeline: scanning -> classification -> manifest inspection -> component
    detection -> relationship discovery -> writing. Each stage is replaceable,
    so later analyzers (manifest analysis, SCIP extraction, graph loading) can
    build on this inventory without redesigning it.
"""

from app.components.architecture_recovery.repository_inventory.catalog import (
    DEFAULT_INVENTORY_OPTIONS,
    InventoryOptions,
)
from app.components.architecture_recovery.repository_inventory.classification import (
    FileClassifier,
)
from app.components.architecture_recovery.repository_inventory.components import (
    ComponentDetector,
    ComponentDetectionResult,
    component_id,
)
from app.components.architecture_recovery.repository_inventory.errors import (
    InventoryScanError,
    InventoryWriteError,
    RepositoryInventoryError,
)
from app.components.architecture_recovery.repository_inventory.manifests import (
    ManifestAnalysis,
    ManifestReader,
)
from app.components.architecture_recovery.repository_inventory.models import (
    SCHEMA_VERSION,
    CandidateComponent,
    Classification,
    ComponentKind,
    Confidence,
    Evidence,
    FileCategory,
    FileRecord,
    InventorySummary,
    Relationship,
    RelationshipType,
    RepositoryInventory,
    RepositoryRef,
)
from app.components.architecture_recovery.repository_inventory.relationships import (
    RelationshipBuilder,
)
from app.components.architecture_recovery.repository_inventory.scanning import (
    RepositoryScanner,
    ScanResult,
    build_file_id,
)
from app.components.architecture_recovery.repository_inventory.service import (
    RepositoryInventoryService,
    default_inventory_service,
    inventory_options_from_settings,
)
from app.components.architecture_recovery.repository_inventory.writer import (
    INVENTORY_FILE_NAME,
    load_inventory,
    write_inventory,
)

__all__ = [
    "INVENTORY_FILE_NAME",
    "SCHEMA_VERSION",
    "CandidateComponent",
    "Classification",
    "ComponentDetectionResult",
    "ComponentDetector",
    "ComponentKind",
    "Confidence",
    "DEFAULT_INVENTORY_OPTIONS",
    "Evidence",
    "FileCategory",
    "FileClassifier",
    "FileRecord",
    "InventoryOptions",
    "InventoryScanError",
    "InventorySummary",
    "InventoryWriteError",
    "ManifestAnalysis",
    "ManifestReader",
    "Relationship",
    "RelationshipBuilder",
    "RelationshipType",
    "RepositoryInventory",
    "RepositoryInventoryError",
    "RepositoryInventoryService",
    "RepositoryRef",
    "RepositoryScanner",
    "ScanResult",
    "build_file_id",
    "component_id",
    "default_inventory_service",
    "inventory_options_from_settings",
    "load_inventory",
    "write_inventory",
]
