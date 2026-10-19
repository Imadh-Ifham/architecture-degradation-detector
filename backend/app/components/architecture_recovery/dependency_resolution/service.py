"""Dependency resolution service.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Orchestrates dependency resolution over the two upstream artifacts and
    persists the report. This service does not clone repositories, does not
    re-run inventory, manifest analysis or component discovery, and does not
    write to Neo4j.

    The API flow passes the reports it already holds; `run_for_ingested` exists
    for callers that have only the artifacts on disk and reads those back
    without repeating any upstream work.
"""

from pathlib import Path

from app.components.architecture_recovery.component_discovery.models import (
    ComponentDiscoveryReport,
)
from app.components.architecture_recovery.component_discovery.writer import (
    COMPONENT_DISCOVERY_FILE_NAME,
    load_component_discovery,
)
from app.components.architecture_recovery.dependency_resolution.errors import (
    DependencyResolutionInputError,
)
from app.components.architecture_recovery.dependency_resolution.models import (
    DependencyResolutionReport,
)
from app.components.architecture_recovery.dependency_resolution.resolver import (
    DependencyResolver,
)
from app.components.architecture_recovery.dependency_resolution.writer import (
    write_dependency_resolution,
)
from app.components.architecture_recovery.manifest_analysis.loader import (
    AnalysisArtifactError,
    load_analysis_report,
)
from app.components.architecture_recovery.manifest_analysis.models import (
    ManifestAnalysisReport,
)
from app.components.architecture_recovery.manifest_analysis.writer import (
    MANIFEST_ANALYSIS_FILE_NAME,
)
from app.domain.repository import IngestedRepository


class DependencyResolutionService:
    """Resolves relationships and writes the dependency resolution artifact."""

    def __init__(self, resolver: DependencyResolver | None = None) -> None:
        """Bind the service to its resolver.

        The resolver defaults to the standard implementation and can be
        replaced, which is the extension point for a future evidence provider.
        """

        self._resolver = resolver or DependencyResolver()

    def resolve(
        self,
        component_discovery: ComponentDiscoveryReport,
        analysis: ManifestAnalysisReport,
    ) -> DependencyResolutionReport:
        """Resolve relationships from the two upstream reports."""

        return self._resolver.resolve(component_discovery, analysis)

    def run(
        self,
        component_discovery: ComponentDiscoveryReport,
        analysis: ManifestAnalysisReport,
        output_directory: Path,
    ) -> tuple[Path, DependencyResolutionReport]:
        """Resolve relationships and write the report into `output_directory`."""

        report = self.resolve(component_discovery, analysis)
        path = write_dependency_resolution(report, output_directory)

        return path, report

    def run_for_ingested(
        self, repository: IngestedRepository
    ) -> tuple[Path, DependencyResolutionReport]:
        """Resolve dependencies for an ingested repository from its artifacts.

        Both upstream documents are read back from the analysis workspace, so
        this entry point re-uses the stages that already ran.
        """

        workspace = repository.path.parent

        try:
            component_document = load_component_discovery(
                workspace / COMPONENT_DISCOVERY_FILE_NAME
            )
        except (OSError, ValueError) as error:
            raise DependencyResolutionInputError(
                f"No readable component discovery at "
                f"'{workspace / COMPONENT_DISCOVERY_FILE_NAME}'; run component "
                f"discovery first: {error}"
            ) from error

        try:
            analysis = load_analysis_report(workspace / MANIFEST_ANALYSIS_FILE_NAME)
        except AnalysisArtifactError as error:
            raise DependencyResolutionInputError(str(error)) from error

        report = self._resolver.resolve_documents(component_document, analysis)
        path = write_dependency_resolution(report, workspace)

        return path, report


def dependency_resolution_service_from_settings() -> DependencyResolutionService:
    """Build a dependency resolution service from the application settings.

    Dependency resolution currently has no tunable limits of its own, so this
    exists to keep the dependency-injection pattern used by the other stages
    and to give a future limit a single place to be read.
    """

    return DependencyResolutionService()


__all__ = [
    "DependencyResolutionService",
    "dependency_resolution_service_from_settings",
]
