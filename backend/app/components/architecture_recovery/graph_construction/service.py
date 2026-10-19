"""Graph construction service.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Builds the version-scoped architecture snapshot for one analyzed revision,
    writes its report, and publishes it to the historical graph store.

    The service reuses the artifacts the earlier recovery stages produced. It
    does not clone, re-inventory, re-analyze manifests, re-run component
    discovery or repeat endpoint resolution. Everything it needs is either an
    in-memory report from the request or a document written by an earlier
    stage.

    Persistence order: the report is written first and the store is written
    second. A report on disk with no graph is recoverable - it says exactly
    what was built and the store can be retried; the reverse would be a graph
    nobody can explain.
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.components.architecture_recovery.component_discovery.models import (
    ComponentDiscoveryReport,
)
from app.components.architecture_recovery.component_discovery.writer import (
    COMPONENT_DISCOVERY_FILE_NAME,
    load_component_discovery,
)
from app.components.architecture_recovery.dependency_resolution.models import (
    DependencyResolutionReport,
)
from app.components.architecture_recovery.dependency_resolution.writer import (
    DEPENDENCY_RESOLUTION_FILE_NAME,
    load_dependency_resolution,
)
from app.components.architecture_recovery.graph_construction.builder import (
    CONFIGURATION,
    CONFIGURATION_KEY,
    GENERATOR_NAME,
    GENERATOR_VERSION,
    SnapshotBuilder,
)
from app.components.architecture_recovery.graph_construction.errors import (
    GraphConstructionInputError,
    SnapshotStoreError,
)
from app.components.architecture_recovery.graph_construction.inputs import (
    SnapshotInputs,
    inputs_from_documents,
    inputs_from_reports,
)
from app.components.architecture_recovery.graph_construction.models import (
    GraphConstructionReport,
    GraphConstructionSummary,
)
from app.components.architecture_recovery.graph_construction.ports import (
    ArchitectureSnapshotStore,
)
from app.components.architecture_recovery.graph_construction.writer import (
    write_graph_construction,
)
from app.components.architecture_recovery.source_code_analysis.models import (
    SourceCodeAnalysisReport,
)
from app.components.architecture_recovery.source_code_analysis.writer import (
    SOURCE_CODE_ANALYSIS_FILE_NAME,
    load_source_code_analysis,
)
from app.domain.architecture_snapshot import (
    AnalysisRun,
    ArchitectureSnapshot,
    ReleaseMetadata,
)
from app.domain.repository import IngestedRepository


class GraphConstructionService:
    """Builds, reports and publishes architecture snapshots."""

    def __init__(
        self,
        store: ArchitectureSnapshotStore | None = None,
        builder: SnapshotBuilder | None = None,
    ) -> None:
        """Bind the service to its store and builder.

        The store is optional only so a caller can inspect a report without a
        database. When one is configured, a refused write is an error: the
        historical graph is the deliverable, not a side effect.
        """

        self._store = store
        self._builder = builder or SnapshotBuilder()

    # ------------------------------------------------------------------ #
    # Entry points
    # ------------------------------------------------------------------ #

    def construct(
        self,
        *,
        release: ReleaseMetadata,
        run: AnalysisRun | None = None,
        discovery: ComponentDiscoveryReport | None = None,
        dependencies: DependencyResolutionReport | None = None,
        source: SourceCodeAnalysisReport | None = None,
    ) -> tuple[ArchitectureSnapshot, GraphConstructionReport]:
        """Build a snapshot from the reports a caller already holds."""

        run = run or new_analysis_run()

        return self._construct(
            release=release,
            run=run,
            inputs=inputs_from_reports(discovery, dependencies, source),
        )

    def run(
        self,
        *,
        release: ReleaseMetadata,
        run: AnalysisRun | None = None,
        discovery: ComponentDiscoveryReport | None = None,
        dependencies: DependencyResolutionReport | None = None,
        source: SourceCodeAnalysisReport | None = None,
        workspace: Path,
    ) -> tuple[Path, GraphConstructionReport]:
        """Build, write the report and publish the snapshot."""

        snapshot, report = self.construct(
            release=release,
            run=run,
            discovery=discovery,
            dependencies=dependencies,
            source=source,
        )

        return self._persist(snapshot, report, Path(workspace))

    def run_for_ingested(
        self, repository: IngestedRepository
    ) -> tuple[Path, GraphConstructionReport]:
        """Build a snapshot from the artifacts written for an ingested clone.

        A missing component-discovery or dependency-resolution document is an
        input error: there is no architecture to persist, and inventing an
        empty one would read downstream as "the release had no components".
        A missing source-code report is different - it is recorded as an
        incomplete snapshot.
        """

        workspace = repository.path.parent
        component_document = self._load_required(
            workspace / COMPONENT_DISCOVERY_FILE_NAME,
            "component discovery",
            load_component_discovery,
        )
        dependency_document = self._load_required(
            workspace / DEPENDENCY_RESOLUTION_FILE_NAME,
            "dependency resolution",
            load_dependency_resolution,
        )
        source_document = self._load_optional(
            workspace / SOURCE_CODE_ANALYSIS_FILE_NAME
        )

        inputs = inputs_from_documents(
            component_document, dependency_document, source_document
        )
        snapshot, report = self._construct(
            release=release_from_ingested(repository),
            run=new_analysis_run(),
            inputs=inputs,
        )

        return self._persist(snapshot, report, workspace)

    def record_failure(
        self,
        *,
        release: ReleaseMetadata,
        error: str,
        run: AnalysisRun | None = None,
        workspace: Path,
        inputs: SnapshotInputs | None = None,
    ) -> tuple[Path, GraphConstructionReport]:
        """Persist a snapshot that records a failed analysis.

        Called when an upstream stage failed. The snapshot is marked `failed`
        and carries no elements, so a consumer never reads a failed run as a
        release whose architecture was removed.
        """

        run = run or new_analysis_run()
        snapshot = self._builder.build_failed(
            release=release, run=run, error=error, inputs=inputs
        )
        report = _report(snapshot, store_published=False)

        return self._persist(snapshot, report, Path(workspace))

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _construct(
        self, *, release: ReleaseMetadata, run: AnalysisRun, inputs: SnapshotInputs
    ) -> tuple[ArchitectureSnapshot, GraphConstructionReport]:
        snapshot = self._builder.build(release=release, run=run, inputs=inputs)

        return snapshot, _report(snapshot, store_published=False)

    def _persist(
        self,
        snapshot: ArchitectureSnapshot,
        report: GraphConstructionReport,
        workspace: Path,
    ) -> tuple[Path, GraphConstructionReport]:
        """Write the report, then publish. A refused publish raises."""

        path = write_graph_construction(report, workspace)
        reference: str | None = None

        if self._store is not None:
            try:
                reference = self._store.publish(snapshot)
            except Exception as error:  # noqa: BLE001
                # Any driver failure is one outcome here: the graph was not
                # written. The report is already on disk and names the error,
                # and the caller must not report a successful snapshot.
                write_graph_construction(
                    _report(snapshot, store_published=False, store_warnings=(str(error),)),
                    workspace,
                )
                raise SnapshotStoreError(
                    f"Could not publish snapshot '{snapshot.snapshot_id}': {error}"
                ) from error

        final = _report(
            snapshot,
            store_published=reference is not None,
            store_reference=reference,
        )
        write_graph_construction(final, workspace)

        return path, final

    @staticmethod
    def _load_required(path: Path, label: str, loader):
        """Load a required artifact, reporting a missing or malformed one."""

        try:
            return loader(path)
        except (OSError, ValueError) as error:
            raise GraphConstructionInputError(
                f"No readable {label} at '{path}'; run the earlier recovery "
                f"stages first: {error}"
            ) from error

    @staticmethod
    def _load_optional(path: Path) -> dict | None:
        """Load an optional artifact, or return None when it is not there."""

        if not path.is_file():
            return None

        try:
            document = load_source_code_analysis(path)
        except (OSError, ValueError):
            return None

        return document if isinstance(document, dict) else None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def new_analysis_run(timestamp: datetime | None = None) -> AnalysisRun:
    """Return a fresh analysis-run identity for this execution.

    A run id is per execution and is *not* part of the snapshot id: rerunning
    one revision reuses the snapshot and only records that a new run happened.
    """

    return AnalysisRun(
        analysis_id=f"analysis:{uuid.uuid4().hex}",
        analysis_timestamp=timestamp or datetime.now(UTC),
        configuration_key=CONFIGURATION_KEY,
        executed_by=GENERATOR_NAME,
    )


def release_from_ingested(repository: IngestedRepository) -> ReleaseMetadata:
    """Build the release metadata of an ingested revision."""

    return ReleaseMetadata(
        repository_id=repository.repository_key,
        commit_sha=repository.commit,
        repository_url=repository.url,
        release_tag=repository.release_tag,
        release_date=repository.release_date,
        release_date_source=repository.release_date_source,
        commit_date=repository.commit_date,
        branch_name=repository.branch,
    )


def _report(
    snapshot: ArchitectureSnapshot,
    *,
    store_published: bool,
    store_reference: str | None = None,
    store_warnings: tuple[str, ...] = (),
) -> GraphConstructionReport:
    """Build the report for a snapshot."""

    return GraphConstructionReport(
        generated_at=datetime.now(UTC),
        snapshot=snapshot,
        summary=GraphConstructionSummary.from_snapshot(snapshot),
        options={
            "configuration": dict(CONFIGURATION),
            "configuration_key": CONFIGURATION_KEY,
            "generator": {"name": GENERATOR_NAME, "version": GENERATOR_VERSION},
            "identity_policy": (
                "A snapshot is keyed by repository, resolved commit and analysis "
                "configuration. A logical element id is its normalised name and "
                "only when that name is unique in the release."
            ),
            "idempotency_policy": (
                "reuse: rerunning one revision under the same configuration "
                "replaces that snapshot's own contents and records the new "
                "analysis run; no other snapshot is touched."
            ),
            "ordering_policy": (
                "release date, else commit date, else analysis timestamp; the "
                "field that answered is recorded on the snapshot"
            ),
        },
        store_published=store_published,
        store_reference=store_reference,
        store_warnings=store_warnings,
        warnings=tuple(snapshot.diagnostics),
    )


def graph_construction_service_from_settings(
    store: ArchitectureSnapshotStore | None = None,
) -> GraphConstructionService:
    """Build a graph construction service from the application settings.

    The store is injected by the API layer because the adapter lives in
    infrastructure and this component may not import it.
    """

    return GraphConstructionService(store=store)


__all__ = [
    "GraphConstructionService",
    "graph_construction_service_from_settings",
    "new_analysis_run",
    "release_from_ingested",
]
