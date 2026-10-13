"""Repository inventory service.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Orchestrates the inventory pipeline: scan, classify, read the manifests
    that matter, detect candidate components, discover relationships, then
    write a single versioned JSON document.

    Each stage is a separate collaborator and can be replaced independently, so
    a future analyzer can extend one stage without touching the others.
"""

from datetime import datetime, timezone
from pathlib import Path

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
)
from app.components.architecture_recovery.repository_inventory.manifests import (
    ManifestAnalysis,
    ManifestReader,
)
from app.components.architecture_recovery.repository_inventory.models import (
    FileCategory,
    FileRecord,
    InventorySummary,
    Relationship,
    RepositoryInventory,
    RepositoryRef,
)
from app.components.architecture_recovery.repository_inventory.relationships import (
    RelationshipBuilder,
)
from app.components.architecture_recovery.repository_inventory.scanning import (
    RepositoryScanner,
    ScanResult,
)
from app.components.architecture_recovery.repository_inventory.writer import (
    write_inventory,
)
from app.core.config import settings
from app.domain.repository import IngestedRepository


# Only these categories are opened for content: they can name a component.
_MANIFEST_CATEGORIES: frozenset[FileCategory] = frozenset(
    {FileCategory.BUILD_MANIFEST, FileCategory.DEPLOYMENT_MANIFEST}
)


class RepositoryInventoryService:
    """Builds a repository inventory and persists it as JSON."""

    def __init__(
        self,
        options: InventoryOptions | None = None,
        manifest_reader: ManifestReader | None = None,
        classifier: FileClassifier | None = None,
        detector: ComponentDetector | None = None,
        relationship_builder: RelationshipBuilder | None = None,
    ) -> None:
        """Bind the service to its stage collaborators.

        Every collaborator defaults to the standard implementation and can be
        replaced, which is the extension point for future analyzers.
        """

        self._options = options or DEFAULT_INVENTORY_OPTIONS
        self._manifest_reader = manifest_reader or ManifestReader(
            max_bytes=self._options.max_manifest_bytes
        )
        self._classifier = classifier or FileClassifier()
        self._detector = detector or ComponentDetector(self._options)
        self._relationship_builder = relationship_builder or RelationshipBuilder()

    def build(
        self,
        root: Path,
        repository: RepositoryRef | None = None,
    ) -> RepositoryInventory:
        """Inventory the working tree at `root` and return the document."""

        root = Path(root)

        scan = RepositoryScanner(root, self._options).scan()

        classifications = [self._classifier.classify(file) for file in scan.files]

        # Classification runs first: only files already known to be manifests
        # are eligible to be opened.
        analyses, manifest_warnings = self._analyse_manifests(root, scan.files)

        detection = self._detector.detect(scan.files, analyses)

        relationships = self._relationship_builder.build(
            scan.files, detection.components, analyses
        )

        return RepositoryInventory(
            generated_at=datetime.now(timezone.utc),
            repository=repository or RepositoryRef(),
            scan_options=self._options.to_dict(),
            summary=self._summarise(scan, detection, relationships),
            files=scan.files,
            classifications=classifications,
            components=detection.components,
            relationships=relationships,
            warnings=[
                *scan.warnings,
                *manifest_warnings,
                *detection.warnings,
            ],
        )

    def run(
        self,
        root: Path,
        output_directory: Path,
        repository: RepositoryRef | None = None,
    ) -> Path:
        """Inventory `root` and write the document into `output_directory`."""

        inventory = self.build(root, repository)
        return write_inventory(inventory, output_directory)

    def run_for_ingested(
        self, repository: IngestedRepository
    ) -> tuple[Path, RepositoryInventory]:
        """Inventory an ingested repository, writing beside its working tree.

        The inventory lands next to `source/` and `metadata.json` so it is
        removed along with the clone and never pollutes the working tree.
        Returns the written path together with the document, so a caller does
        not have to read the file back.
        """

        reference = RepositoryRef(
            id=repository.id,
            url=repository.url,
            branch=repository.branch,
            commit=repository.commit,
        )

        inventory = self.build(repository.path, reference)
        path = write_inventory(inventory, repository.path.parent)

        return path, inventory

    def _analyse_manifests(
        self, root: Path, files: list[FileRecord]
    ) -> tuple[dict[str, ManifestAnalysis], list[str]]:
        """Read the manifests that can name a component.

        Returns the findings keyed by file id, plus any parse warnings.
        """

        analyses: dict[str, ManifestAnalysis] = {}
        warnings: list[str] = []

        for file in files:
            if file.category not in _MANIFEST_CATEGORIES:
                continue

            analysis = self._manifest_reader.analyse(file, root / file.path)
            analyses[file.id] = analysis

            if analysis.warning:
                warnings.append(analysis.warning)

        return analyses, warnings

    @staticmethod
    def _summarise(
        scan: ScanResult,
        detection: ComponentDetectionResult,
        relationships: list[Relationship],
    ) -> InventorySummary:
        """Aggregate the run's counts for the document's summary section."""

        by_category: dict[str, int] = {}
        by_language: dict[str, int] = {}
        total_size_bytes = 0

        for file in scan.files:
            by_category[file.category.value] = (
                by_category.get(file.category.value, 0) + 1
            )

            if file.language:
                by_language[file.language] = by_language.get(file.language, 0) + 1

            total_size_bytes += file.size_bytes

        return InventorySummary(
            file_count=len(scan.files),
            total_size_bytes=total_size_bytes,
            excluded_file_count=scan.excluded_file_count,
            excluded_directory_count=scan.excluded_directory_count,
            unreadable_count=scan.unreadable_count,
            truncated=scan.truncated,
            component_count=len(detection.components),
            relationship_count=len(relationships),
            # Sorted so the summary is stable between runs.
            by_category=dict(sorted(by_category.items())),
            by_language=dict(sorted(by_language.items())),
        )


def inventory_options_from_settings() -> InventoryOptions:
    """Build scan options from application settings.

    Exclusions are extended through a comma-separated setting, so a project
    with an unusual layout can be scanned without changing code.
    """

    extra_directories = tuple(
        item.strip()
        for item in settings.inventory_extra_excluded_directories.split(",")
        if item.strip()
    )

    return InventoryOptions(
        max_files=settings.inventory_max_files,
        max_file_size_bytes=settings.inventory_max_file_size_bytes,
        max_depth=settings.inventory_max_depth,
        max_manifest_bytes=settings.inventory_max_manifest_bytes,
        grouping_depth=settings.inventory_grouping_depth,
        extra_excluded_directories=extra_directories,
    )


def default_inventory_service() -> RepositoryInventoryService:
    """Build a service configured from the application settings."""

    return RepositoryInventoryService(options=inventory_options_from_settings())
