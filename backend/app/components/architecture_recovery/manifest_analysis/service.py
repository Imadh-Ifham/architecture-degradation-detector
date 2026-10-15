"""Manifest analysis service.

Author: Imadh Ifham
Date: 2026-10-14
Description:
    Orchestrates manifest analysis: take a repository inventory, analyze only
    the files it classifies as manifests, and produce one report.

    Responsibilities stay separate by design: this service does not traverse the
    repository (the inventory did that), does not clone anything (the ingestion
    stage did that), resolves nothing outside a single file (cross-file
    dependency resolution is a later stage), and never writes to Neo4j (graph
    construction is a later stage).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from app.components.architecture_recovery.manifest_analysis.base import (
    AnalyzerResult,
)
from app.components.architecture_recovery.manifest_analysis.errors import (
    AnalysisInputError,
)
from app.components.architecture_recovery.manifest_analysis.models import (
    DeclaredRelationship,
    DeclaredResource,
    DiagnosticSeverity,
    Endpoint,
    FileAnalysisResult,
    ManifestAnalysisReport,
    ManifestAnalysisSummary,
    ParseStatus,
    ResourceReference,
    ReferenceStatus,
)
from app.components.architecture_recovery.manifest_analysis.registry import (
    AnalyzerRegistry,
)
from app.components.architecture_recovery.manifest_analysis.writer import (
    write_manifest_analysis,
)
from app.components.architecture_recovery.repository_inventory.models import (
    CandidateComponent,
    FileCategory,
    FileRecord,
    InventorySummary,
    RepositoryInventory,
    RepositoryRef,
)
from app.components.architecture_recovery.repository_inventory.writer import (
    INVENTORY_FILE_NAME,
)
from app.core.config import settings
from app.domain.repository import IngestedRepository


class ManifestAnalysisService:
    """Analyzes the manifests an inventory found and persists the report."""

    def __init__(
        self,
        registry: AnalyzerRegistry | None = None,
        max_bytes: int = 1_048_576,
        max_documents: int = 64,
    ) -> None:
        """Bind the service to an analyzer registry and its limits."""

        self._max_bytes = max_bytes
        self._max_documents = max_documents
        self._registry = registry or AnalyzerRegistry(
            max_bytes=max_bytes, max_documents=max_documents
        )

    def analyze(
        self, inventory: RepositoryInventory, root: Path
    ) -> ManifestAnalysisReport:
        """Analyze the manifests recorded in `inventory`, read from `root`."""

        root = Path(root)

        results: list[FileAnalysisResult] = []
        resources: list[DeclaredResource] = []
        relationships: list[DeclaredRelationship] = []
        endpoints: list[Endpoint] = []
        references: list[ResourceReference] = []

        # Sorted so the analysis is deterministic regardless of scan order.
        for file in sorted(inventory.files, key=lambda item: item.path):
            if not self._registry.is_candidate(file):
                # Source code, tests, documentation and formats this stage does
                # not claim are deliberately not reported on.
                continue

            analyzer = self._registry.select(file)

            if analyzer is None:
                results.append(self._unsupported(file))
                continue

            analysis = analyzer.analyze(file, root / file.path)

            results.append(analysis.to_file_result(file.path, analyzer.name))
            resources.extend(analysis.resources)
            relationships.extend(analysis.relationships)
            endpoints.extend(analysis.endpoints)
            references.extend(analysis.references)

        return ManifestAnalysisReport(
            generated_at=datetime.now(timezone.utc),
            repository=inventory.repository,
            options={
                "max_bytes": self._max_bytes,
                "max_documents": self._max_documents,
                "analyzers": self._registry.names(),
            },
            summary=self._summarise(results, resources, relationships, endpoints, references),
            results=results,
            resources=sorted(
                resources, key=lambda item: (item.location.path, item.kind.value, item.name)
            ),
            relationships=sorted(
                relationships,
                key=lambda item: (
                    item.location.path,
                    item.type.value,
                    item.source_id,
                    item.target_id,
                ),
            ),
            endpoints=sorted(
                endpoints, key=lambda item: (item.location.path, item.id)
            ),
            references=sorted(
                references,
                key=lambda item: (
                    item.location.path,
                    item.kind.value,
                    item.name,
                    item.reference_type,
                ),
            ),
            warnings=self._warnings(results),
        )

    def run(
        self,
        inventory: RepositoryInventory,
        root: Path,
        output_directory: Path,
    ) -> tuple[Path, ManifestAnalysisReport]:
        """Analyze `inventory` and write the report into `output_directory`."""

        report = self.analyze(inventory, root)
        path = write_manifest_analysis(report, output_directory)

        return path, report

    def run_for_ingested(
        self, repository: IngestedRepository
    ) -> tuple[Path, ManifestAnalysisReport]:
        """Analyze an ingested repository using the inventory already on disk.

        The inventory is read, never rebuilt: scanning is the inventory's job.
        """

        inventory_path = repository.path.parent / INVENTORY_FILE_NAME
        inventory = load_inventory(inventory_path)

        return self.run(inventory, repository.path, repository.path.parent)

    def _unsupported(self, file: FileRecord) -> FileAnalysisResult:
        """Record a manifest file that no analyzer claims."""

        result = AnalyzerResult(status=ParseStatus.SKIPPED)
        result.add_diagnostic(
            DiagnosticSeverity.WARNING,
            "no analyzer supports this manifest format; it was not analyzed",
            file.path,
            None,
            None,
        )

        return result.to_file_result(file.path, None)

    @staticmethod
    def _warnings(results: list[FileAnalysisResult]) -> list[str]:
        """Collect warning and error diagnostics into a quick-scan list."""

        warnings = []

        for result in results:
            for diagnostic in result.diagnostics:
                if diagnostic.severity in (
                    DiagnosticSeverity.WARNING,
                    DiagnosticSeverity.ERROR,
                ):
                    warnings.append(f"{result.path}: {diagnostic.message}")

        return warnings

    @staticmethod
    def _summarise(
        results: list[FileAnalysisResult],
        resources: list[DeclaredResource],
        relationships: list[DeclaredRelationship],
        endpoints: list[Endpoint],
        references: list[ResourceReference],
    ) -> ManifestAnalysisSummary:
        """Aggregate the run's counts for the report's summary section."""

        by_analyzer: dict[str, int] = {}
        analyzed = skipped = failed = 0

        for result in results:
            if result.status is ParseStatus.SKIPPED:
                skipped += 1
            elif result.status is ParseStatus.FAILED:
                failed += 1
            else:
                analyzed += 1

            if result.analyzer:
                by_analyzer[result.analyzer] = by_analyzer.get(result.analyzer, 0) + 1

        return ManifestAnalysisSummary(
            file_count=len(results),
            analyzed_count=analyzed,
            skipped_count=skipped,
            failed_count=failed,
            resource_count=len(resources),
            relationship_count=len(relationships),
            endpoint_count=len(endpoints),
            unresolved_reference_count=sum(
                1
                for item in references
                if item.status is ReferenceStatus.UNRESOLVED
            ),
            # Sorted so the summary is stable between runs.
            by_analyzer=dict(sorted(by_analyzer.items())),
        )


def load_inventory(path: Path) -> RepositoryInventory:
    """Rebuild an inventory from the JSON the inventory stage wrote.

    Only the fields this stage consumes are reconstructed; the report references
    the same repository identity so the two documents stay linkable.
    """

    path = Path(path)

    if not path.is_file():
        raise AnalysisInputError(
            f"No repository inventory at '{path}'; run the inventory first."
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AnalysisInputError(
            f"Could not read the repository inventory at '{path}': {error}"
        ) from error

    try:
        files = [_file_from_dict(item) for item in payload.get("files", [])]
        components = [
            CandidateComponent.from_dict(item)
            for item in payload.get("components", [])
        ]
    except (AttributeError, TypeError, KeyError) as error:
        raise AnalysisInputError(
            f"Repository inventory at '{path}' has an unexpected structure: {error}"
        ) from error

    repository = payload.get("repository") or {}

    return RepositoryInventory(
        generated_at=datetime.now(timezone.utc),
        repository=RepositoryRef(
            id=repository.get("id"),
            url=repository.get("url"),
            branch=repository.get("branch"),
            commit=repository.get("commit"),
        ),
        scan_options=payload.get("scan_options") or {},
        summary=_empty_summary(),
        files=files,
        # The candidate components are rebuilt too, because a later stage needs
        # the source-project boundaries the inventory already established rather
        # than re-deriving them from the files.
        components=components,
    )


def _file_from_dict(item: dict) -> FileRecord:
    """Rebuild the file fields manifest analysis depends on."""

    return FileRecord(
        id=item["id"],
        path=item["path"],
        name=item["name"],
        extension=item.get("extension") or "",
        size_bytes=int(item.get("size_bytes") or 0),
        depth=int(item.get("depth") or 0),
        language=item.get("language"),
        format=item.get("format"),
        category=_category(item.get("category")),
        component_id=item.get("component_id"),
    )


def _category(value: object) -> FileCategory:
    """Map a serialised category back to its enum, tolerating unknown values."""

    try:
        return FileCategory(value)  # type: ignore[arg-type]
    except ValueError:
        return FileCategory.UNKNOWN


def _empty_summary() -> InventorySummary:
    """Return a placeholder inventory summary for a reconstructed inventory.

    Manifest analysis does not consume inventory counts, so they are not
    recomputed when the inventory is loaded back from disk.
    """

    return InventorySummary()


def manifest_analysis_service_from_settings() -> ManifestAnalysisService:
    """Build a service configured from the application settings."""

    return ManifestAnalysisService(
        max_bytes=settings.manifest_max_bytes,
        max_documents=settings.manifest_max_documents,
    )
