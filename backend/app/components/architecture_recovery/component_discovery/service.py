"""Component discovery service.

Author: Imadh Ifham
Date: 2026-10-15
Description:
    Orchestrates component discovery: collect candidate artifacts from the
    inventory and manifest analysis, resolve their identities, assemble
    components with their artifacts, and produce one report.

    Responsibilities stay separate by design. This service does not clone
    repositories, does not re-walk the repository, does not parse manifests, does
    not infer cross-service calls from names, and does not write to Neo4j. It
    answers one question: which logical components exist, and which artifacts
    belong to each.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from app.components.architecture_recovery.component_discovery.association import (
    ComponentAssembler,
)
from app.components.architecture_recovery.component_discovery.candidates import (
    CandidateCollector,
)
from app.components.architecture_recovery.component_discovery.errors import (
    DiscoveryInputError,
)
from app.components.architecture_recovery.component_discovery.identity import (
    IdentityResolver,
)
from app.components.architecture_recovery.component_discovery.models import (
    ASSOCIATION_BY_ROLE,
    DIRECT_RULES,
    IDENTITY_POLICY,
    AssociationConfidence,
    ComponentDiscoveryReport,
    ComponentDiscoverySummary,
    RepositoryRef,
)
from app.components.architecture_recovery.component_discovery.writer import (
    write_component_discovery,
)
from app.components.architecture_recovery.manifest_analysis.loader import (
    AnalysisArtifactError,
    load_analysis_report,
)
from app.components.architecture_recovery.manifest_analysis.models import (
    DiagnosticSeverity,
    ManifestAnalysisReport,
)
from app.components.architecture_recovery.manifest_analysis.service import (
    AnalysisInputError,
    load_inventory,
)
from app.components.architecture_recovery.manifest_analysis.writer import (
    MANIFEST_ANALYSIS_FILE_NAME,
)
from app.components.architecture_recovery.repository_inventory.models import (
    RepositoryInventory,
)
from app.components.architecture_recovery.repository_inventory.writer import (
    INVENTORY_FILE_NAME,
)
from app.domain.repository import IngestedRepository


#: Explanation of the confidence categories, recorded in the output so a
#: consumer does not have to infer the semantics from the source.
CONFIDENCE_SEMANTICS: dict[str, str] = {
    "direct": (
        "explicit, machine-checkable evidence: a declared build context, a path "
        "containment relationship, a shared application image, or a name match "
        "corroborated by location"
    ),
    "heuristic": (
        "suggestive evidence only: a name match with no location link, or "
        "directory structure on its own"
    ),
}


class ComponentDiscoveryService:
    """Discovers logical components and associates artifacts with them."""

    def __init__(
        self,
        collector: CandidateCollector | None = None,
        resolver: IdentityResolver | None = None,
        assembler: ComponentAssembler | None = None,
    ) -> None:
        """Bind the service to its stage collaborators.

        Every collaborator defaults to the standard implementation and can be
        replaced, which is the extension point for a future identity policy.
        """

        self._collector = collector or CandidateCollector()
        self._resolver = resolver or IdentityResolver()
        self._assembler = assembler or ComponentAssembler()

    def discover(
        self,
        inventory: RepositoryInventory,
        analysis: ManifestAnalysisReport,
    ) -> ComponentDiscoveryReport:
        """Discover components from the two upstream artifacts.

        Both the inventory and manifest analysis are required: without the
        inventory there are no source projects or files, and without manifest
        analysis there are no deployment declarations or contracts. Each input is
        used as-is rather than re-derived.
        """

        collection = self._collector.collect(inventory, analysis)
        groups = self._resolver.resolve(collection.candidates)
        assembly = self._assembler.assemble(
            collection.candidates, groups, collection.diagnostics
        )

        return ComponentDiscoveryReport(
            generated_at=datetime.now(timezone.utc),
            repository=inventory.repository,
            options={
                "identity_policy": IDENTITY_POLICY,
                "confidence_semantics": CONFIDENCE_SEMANTICS,
                "direct_rules": sorted(rule.value for rule in DIRECT_RULES),
                "candidate_count": len(collection.candidates),
            },
            summary=_summarise(assembly),
            components=assembly.components,
            artifacts=assembly.artifacts,
            unresolved=assembly.unresolved,
            ambiguous=assembly.ambiguous,
            diagnostics=assembly.diagnostics,
            warnings=[
                f"{diagnostic.path}: {diagnostic.message}"
                for diagnostic in assembly.diagnostics
                if diagnostic.severity
                in (DiagnosticSeverity.WARNING, DiagnosticSeverity.ERROR)
            ],
        )

    def run(
        self,
        inventory: RepositoryInventory,
        analysis: ManifestAnalysisReport,
        output_directory: Path,
    ) -> tuple[Path, ComponentDiscoveryReport]:
        """Discover components and write the report into `output_directory`."""

        report = self.discover(inventory, analysis)
        path = write_component_discovery(report, output_directory)

        return path, report

    def run_for_ingested(
        self, repository: IngestedRepository
    ) -> tuple[Path, ComponentDiscoveryReport]:
        """Discover components for an ingested repository from its artifacts.

        Both upstream documents are read back from the analysis workspace, so
        this entry point re-uses the stages that already ran rather than
        repeating any of their work.
        """

        workspace = repository.path.parent

        # A missing or malformed upstream artifact is an input problem, so both
        # loaders' errors are reported as one input failure with the reason.
        try:
            inventory = load_inventory(workspace / INVENTORY_FILE_NAME)
        except AnalysisInputError as error:
            raise DiscoveryInputError(str(error)) from error

        try:
            analysis = load_analysis_report(workspace / MANIFEST_ANALYSIS_FILE_NAME)
        except AnalysisArtifactError as error:
            raise DiscoveryInputError(str(error)) from error

        return self.run(inventory, analysis, workspace)


def _summarise(assembly) -> ComponentDiscoverySummary:
    """Aggregate the run's counts for the report's summary section."""

    by_type: dict[str, int] = {}
    by_confidence: dict[str, int] = {}
    by_association: dict[str, int] = {}
    names: dict[str, int] = {}

    for component in assembly.components:
        by_type[component.type.value] = by_type.get(component.type.value, 0) + 1
        by_confidence[component.confidence.value] = (
            by_confidence.get(component.confidence.value, 0) + 1
        )
        key = component.name.lower()
        names[key] = names.get(key, 0) + 1

    direct = heuristic = 0

    for artifact in assembly.artifacts:
        by_association[artifact.association.value] = (
            by_association.get(artifact.association.value, 0) + 1
        )

        if artifact.confidence is AssociationConfidence.DIRECT:
            direct += 1
        else:
            heuristic += 1

    # A name shared by more than one component means the same logical name was
    # resolved to several identities, which is worth surfacing rather than hiding.
    duplicates = sum(count - 1 for count in names.values() if count > 1)

    return ComponentDiscoverySummary(
        component_count=len(assembly.components),
        artifact_count=len(assembly.artifacts),
        unresolved_count=len(assembly.unresolved),
        ambiguous_count=len(assembly.ambiguous),
        duplicate_identity_count=duplicates,
        direct_association_count=direct,
        heuristic_association_count=heuristic,
        by_type=dict(sorted(by_type.items())),
        by_confidence=dict(sorted(by_confidence.items())),
        by_association=dict(sorted(by_association.items())),
    )


def component_discovery_service_from_settings() -> ComponentDiscoveryService:
    """Build a discovery service from the application settings.

    Component discovery currently has no tunable limits of its own, so this
    exists to keep the dependency-injection pattern used by the other stages
    and to give a future limit a single place to be read.
    """

    return ComponentDiscoveryService()


__all__ = [
    "ComponentDiscoveryService",
    "component_discovery_service_from_settings",
]
