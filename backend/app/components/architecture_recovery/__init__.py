"""Architecture recovery component.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Reconstructs the architecture of a system as it actually is (the as-is
    model used by every later research stage). Exposes repository ingestion,
    repository inventory, manifest analysis, component discovery, dependency
    resolution and source code analysis.
"""

from app.components.architecture_recovery.component_discovery.service import (
    ComponentDiscoveryService,
)
from app.components.architecture_recovery.dependency_resolution.service import (
    DependencyResolutionService,
)
from app.components.architecture_recovery.manifest_analysis.service import (
    ManifestAnalysisService,
)
from app.components.architecture_recovery.repository_ingestion.service import (
    RepositoryIngestionService,
)
from app.components.architecture_recovery.repository_inventory.service import (
    RepositoryInventoryService,
)
from app.components.architecture_recovery.source_code_analysis.service import (
    SourceCodeAnalysisService,
)

__all__ = [
    "ComponentDiscoveryService",
    "DependencyResolutionService",
    "ManifestAnalysisService",
    "RepositoryIngestionService",
    "RepositoryInventoryService",
    "SourceCodeAnalysisService",
]
