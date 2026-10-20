"""Repository ingestion and recovery endpoints.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Exposes repository setup, ingestion, recovery, and removal over HTTP.

    **Three separate acts, deliberately not one endpoint.** Configuring a
    snapshot writes down what should be analysed and touches nothing else.
    Ingesting clones it. Recovering analyses the clone stage by stage. A
    caller that only wanted to write down a release does not pay for a clone,
    and a caller that wants to analyse many snapshots decides the order
    itself - which is what the pipeline does.

    A recovery runs that clone through a repository inventory, manifest
    analysis, component discovery, dependency resolution, source code analysis
    and graph construction, and each stage's summary is included in the
    response. The subcomponents stay independent: this transport layer is the
    only place that knows the order in which they run.

    Release-aware ingestion is available through `POST /repositories/releases`
    or by naming `revision` on `POST /repositories`, and the resulting history
    through `GET /repositories/{id}/snapshots`. Both read and write the same
    graph store that graph construction publishes to.
"""

from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.components.architecture_recovery.component_discovery import (
    ComponentDiscoveryError,
    ComponentDiscoveryReport,
    ComponentDiscoveryService,
    ComponentDiscoverySummaryResponse,
    component_discovery_service_from_settings,
)
from app.components.architecture_recovery.dependency_resolution import (
    DependencyResolutionError,
    DependencyResolutionReport,
    DependencyResolutionService,
    DependencyResolutionSummaryResponse,
    dependency_resolution_service_from_settings,
)
from app.components.architecture_recovery.graph_construction import (
    ArchitectureSnapshotStore,
    GraphConstructionError,
    GraphConstructionService,
    GraphConstructionSummaryResponse,
    SnapshotSummaryResponse,
    graph_construction_service_from_settings,
    release_from_ingested,
)
from app.components.architecture_recovery.manifest_analysis import (
    ManifestAnalysisError,
    ManifestAnalysisReport,
    ManifestAnalysisService,
    ManifestAnalysisSummaryResponse,
    manifest_analysis_service_from_settings,
)
from app.components.architecture_recovery.repository_ingestion.errors import (
    InvalidRepositorySource,
    RepositoryNotFound,
)
from app.components.architecture_recovery.repository_ingestion.schemas import (
    IngestedRepositoryResponse,
    RepositoryIngestionRequest,
    RepositoryReleaseRequest,
)
from app.components.architecture_recovery.repository_ingestion.service import (
    SOURCE_DIRECTORY_NAME,
)
from app.components.architecture_recovery.repository_ingestion.service import (
    RepositoryIngestionService,
)
from app.components.architecture_recovery.repository_ingestion.validation import (
    redact_credentials,
    validate_branch,
    validate_release_tag,
    validate_url,
)
from app.components.architecture_recovery.repository_inventory import (
    RepositoryInventory,
    RepositoryInventoryError,
    RepositoryInventoryService,
    RepositoryInventorySummaryResponse,
    inventory_options_from_settings,
)
from app.components.architecture_recovery.recovery_run import (
    STAGE_BY_NAME,
    StageRecord,
    StageTimer,
    build_report,
    build_run,
    now,
    write_run,
)
from app.components.architecture_recovery.snapshot_details import SnapshotDetails
from app.components.architecture_recovery.source_code_analysis import (
    SourceCodeAnalysisError,
    SourceCodeAnalysisReport,
    SourceCodeAnalysisService,
    SourceCodeAnalysisSummaryResponse,
    source_code_analysis_service_from_settings,
)
from app.components.architecture_validation.observation_normalization import (
    UnorderableRelease,
    release_sort_key,
)
from app.core.config import settings
from app.domain.repository import IngestedRepository
from app.domain.repository_configuration import (
    RepositoryConfiguration,
    configuration_id_for,
)
from app.infrastructure.git.client import GitClient, GitCommandError
from app.infrastructure.workspace import (
    ConfigurationStoreError,
    RepositoryConfigurationStore,
    WorkspaceCheckouts,
)

router = APIRouter(prefix="/repositories", tags=["Repositories"])


class RecoveryResponse(IngestedRepositoryResponse):
    """A recovered repository: the clone's record plus each stage's summary.

    Each optional block is null when its stage could not run, in which case the
    matching `*_error` explains why. The clone itself is unaffected either way,
    and a snapshot that reached graph construction is what validation reads.
    """

    inventory: RepositoryInventorySummaryResponse | None = None
    inventory_error: str | None = None
    manifest_analysis: ManifestAnalysisSummaryResponse | None = None
    manifest_analysis_error: str | None = None
    component_discovery: ComponentDiscoverySummaryResponse | None = None
    component_discovery_error: str | None = None
    dependency_resolution: DependencyResolutionSummaryResponse | None = None
    dependency_resolution_error: str | None = None
    source_code_analysis: SourceCodeAnalysisSummaryResponse | None = None
    source_code_analysis_error: str | None = None
    graph_construction: GraphConstructionSummaryResponse | None = None
    graph_construction_error: str | None = None


class RepositoryConfigurationRequest(BaseModel):
    """Body of `POST /repositories/configurations`.

    The three fields are a snapshot's whole identity. The release tag is
    required because it is what names the revision downstream - recovery
    identifies a checkout by commit, and a commit carries no order for the
    decision history to compare releases against.
    """

    url: str = Field(min_length=1, max_length=2048)
    branch: str = Field(min_length=1, max_length=255)
    release_tag: str = Field(min_length=1, max_length=255)


class RepositoryConfigurationResponse(BaseModel):
    """One configured snapshot. Nothing has been cloned or analysed."""

    id: str
    url: str
    branch: str
    release_tag: str
    created_at: str

    @classmethod
    def from_record(cls, record: RepositoryConfiguration) -> "RepositoryConfigurationResponse":
        return cls(**record.to_dict())


@lru_cache
def get_git_client() -> GitClient:
    """Provide a process-wide git client built from the configured timeout."""

    return GitClient(timeout_seconds=settings.clone_timeout_seconds)


@lru_cache
def get_repository_ingestion_service() -> RepositoryIngestionService:
    """Provide the ingestion service shared by all requests.

    Cached so the workspace settings are read once. Declared as a FastAPI
    dependency so tests can override it.
    """

    return RepositoryIngestionService(
        git_client=get_git_client(),
        root=settings.repositories_root,
    )


@lru_cache
def get_repository_inventory_service() -> RepositoryInventoryService:
    """Provide the inventory service shared by all requests.

    Cached so the scan limits are read once. Declared as a FastAPI dependency
    so tests can override it.
    """

    return RepositoryInventoryService(options=inventory_options_from_settings())


@lru_cache
def get_manifest_analysis_service() -> ManifestAnalysisService:
    """Provide the manifest analysis service shared by all requests.

    Cached so the analysis limits are read once, and declared as a FastAPI
    dependency so tests can override it.
    """

    return manifest_analysis_service_from_settings()


@lru_cache
def get_component_discovery_service() -> ComponentDiscoveryService:
    """Provide the component discovery service shared by all requests.

    Declared as a FastAPI dependency so tests can override it.
    """

    return component_discovery_service_from_settings()


@lru_cache
def get_dependency_resolution_service() -> DependencyResolutionService:
    """Provide the dependency resolution service shared by all requests.

    Declared as a FastAPI dependency so tests can override it.
    """

    return dependency_resolution_service_from_settings()


@lru_cache
def get_source_code_analysis_service() -> SourceCodeAnalysisService:
    """Provide the source code analysis service shared by all requests.

    Declared as a FastAPI dependency so tests can override it.
    """

    return source_code_analysis_service_from_settings()


@lru_cache
def get_architecture_snapshot_store() -> ArchitectureSnapshotStore:
    """Provide the historical graph store.

    Imported lazily so a deployment without a configured graph store can still
    serve the ingestion endpoints; the failure then lands on the stage that
    needed it rather than at import time.
    """

    from app.infrastructure.neo4j.architecture_snapshot_store import (
        Neo4jArchitectureSnapshotStore,
    )
    from app.infrastructure.neo4j.database import driver

    return Neo4jArchitectureSnapshotStore(driver.session)


@lru_cache
def get_graph_construction_service() -> GraphConstructionService:
    """Provide the graph construction service shared by all requests.

    Declared as a FastAPI dependency so tests can override it.
    """

    return graph_construction_service_from_settings(
        store=get_architecture_snapshot_store()
    )


@lru_cache
def get_configuration_store() -> RepositoryConfigurationStore:
    """Provide the store the configured snapshots live in.

    The workspace root rather than a setting of its own: a configured snapshot
    and the clone it later produces belong to the same workspace, and two
    roots would let one be deleted while the other still pointed at it.
    """

    return RepositoryConfigurationStore(settings.repositories_root)


@lru_cache
def get_workspace_checkouts() -> WorkspaceCheckouts:
    """Provide the resolver that finds a release's checkout.

    Declared as a dependency so a test can point it at the workspace it built
    rather than at the machine's own.
    """

    return WorkspaceCheckouts(settings.repositories_root, SOURCE_DIRECTORY_NAME)


@router.post(
    "",
    response_model=IngestedRepositoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def ingest_repository(
    request: RepositoryIngestionRequest,
    service: RepositoryIngestionService = Depends(get_repository_ingestion_service),
) -> IngestedRepositoryResponse:
    """Clone the named revision, or the branch tip, and nothing else.

    Analysis is a separate call (`POST /repositories/{id}/recovery`) so that
    the clone and the pipeline can fail, retry and be ordered independently.
    """

    try:
        if request.revision and request.revision.strip():
            repository = service.ingest_revision(
                request.url, request.revision.strip(), request.branch
            )
        else:
            repository = service.ingest(request.url, request.branch)
    except InvalidRepositorySource as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error
    except GitCommandError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=redact_credentials(_describe_git_failure(error)),
        ) from error

    return IngestedRepositoryResponse.model_validate(repository)


@router.post(
    "/releases",
    response_model=IngestedRepositoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def ingest_release(
    request: RepositoryReleaseRequest,
    service: RepositoryIngestionService = Depends(get_repository_ingestion_service),
) -> IngestedRepositoryResponse:
    """Clone one explicit revision and record it as its own checkout.

    Kept beside the `revision` field on `POST /repositories` because both are
    one act; neither runs the pipeline.
    """

    try:
        repository = service.ingest_revision(
            request.url, request.revision, request.branch
        )
    except InvalidRepositorySource as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error
    except GitCommandError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=redact_credentials(_describe_git_failure(error)),
        ) from error

    return IngestedRepositoryResponse.model_validate(repository)


@router.post(
    "/{repository_id}/recovery",
    response_model=RecoveryResponse,
    summary="Run architecture recovery over an ingested repository",
    response_description=(
        "One summary per recovery stage. A stage that could not run reports "
        "itself in `<stage>_error` rather than failing the request."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "That repository has not been ingested on this machine."
        }
    },
)
def recover_repository(
    repository_id: str,
    service: RepositoryIngestionService = Depends(get_repository_ingestion_service),
    inventory_service: RepositoryInventoryService = Depends(
        get_repository_inventory_service
    ),
    analysis_service: ManifestAnalysisService = Depends(
        get_manifest_analysis_service
    ),
    discovery_service: ComponentDiscoveryService = Depends(
        get_component_discovery_service
    ),
    dependency_service: DependencyResolutionService = Depends(
        get_dependency_resolution_service
    ),
    source_analysis_service: SourceCodeAnalysisService = Depends(
        get_source_code_analysis_service
    ),
    graph_service: GraphConstructionService = Depends(get_graph_construction_service),
) -> RecoveryResponse:
    """Run every recovery stage over an already-cloned repository.

    Separate from ingestion on purpose: the clone is the expensive, failure
    prone step a caller may retry alone, and the pipeline needs to run one
    snapshot at a time in an order it chooses.
    """

    try:
        repository = service.get(repository_id)
    except RepositoryNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error

    return _analyse(
        repository,
        inventory_service,
        analysis_service,
        discovery_service,
        dependency_service,
        source_analysis_service,
        graph_service,
    )


@router.get("", response_model=list[IngestedRepositoryResponse])
def list_repositories(
    service: RepositoryIngestionService = Depends(get_repository_ingestion_service),
) -> list[IngestedRepositoryResponse]:
    """List every repository currently held in the workspace."""

    return [
        IngestedRepositoryResponse.model_validate(repository)
        for repository in service.list_ingested()
    ]


@router.get(
    "/configurations",
    response_model=list[RepositoryConfigurationResponse],
    summary="List the configured snapshots",
    response_description="Every saved snapshot, in the order it was configured.",
)
def list_configurations(
    store: RepositoryConfigurationStore = Depends(get_configuration_store),
) -> list[RepositoryConfigurationResponse]:
    """Return what has been configured. Nothing is cloned by this call."""

    try:
        records = store.list()
    except ConfigurationStoreError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error)
        ) from error

    return [RepositoryConfigurationResponse.from_record(record) for record in records]


@router.post(
    "/configurations",
    response_model=RepositoryConfigurationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Configure a snapshot without cloning it",
    response_description=(
        "The saved snapshot. Nothing has been cloned and nothing has been analysed."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "A field is not a usable repository url, branch or "
            "orderable release tag."
        }
    },
)
def save_configuration(
    request: RepositoryConfigurationRequest,
    store: RepositoryConfigurationStore = Depends(get_configuration_store),
) -> RepositoryConfigurationResponse:
    """Write down one snapshot for a later pipeline run.

    Everything a release needs to be *identified* is checked here, including
    that its tag can be ordered against other releases. An unorderable tag
    would let the pipeline recover three snapshots and then refuse to validate
    all three, which is a failure this call can prevent for free.
    """

    try:
        url = validate_url(request.url)
        branch = validate_branch(request.branch)
        release_tag = validate_release_tag(request.release_tag)
        release_sort_key(release_tag)
    except InvalidRepositorySource as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    except UnorderableRelease as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error

    record = RepositoryConfiguration(
        id=configuration_id_for(url, branch, release_tag),
        url=url,
        branch=branch,
        release_tag=release_tag,
        created_at=datetime.now(UTC),
    )

    try:
        stored = store.save(record)
    except ConfigurationStoreError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error)
        ) from error

    return RepositoryConfigurationResponse.from_record(stored)


@router.delete(
    "/configurations/{configuration_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_configuration(
    configuration_id: str,
    store: RepositoryConfigurationStore = Depends(get_configuration_store),
) -> None:
    """Stop a snapshot being part of the next run. Nothing else is touched."""

    try:
        removed = store.delete(configuration_id)
    except ConfigurationStoreError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error)
        ) from error

    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No configured snapshot '{configuration_id}'.",
        )


@router.get(
    "/{repository_id}/snapshots",
    response_model=list[SnapshotSummaryResponse],
)
def list_snapshots(
    repository_id: str,
    store: ArchitectureSnapshotStore = Depends(get_architecture_snapshot_store),
) -> list[SnapshotSummaryResponse]:
    """List a repository's architecture snapshots, oldest first.

    Ordering uses the release date where one exists, then the commit date, then
    the analysis timestamp; each row says which field placed it.
    """

    try:
        history = store.history(repository_id)
    except Exception as error:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Graph store unavailable: {error}",
        ) from error

    return [SnapshotSummaryResponse.from_summary(item) for item in history]


@router.get("/{repository_id}/snapshots/{snapshot_id}")
def read_snapshot(
    repository_id: str,
    snapshot_id: str,
    store: ArchitectureSnapshotStore = Depends(get_architecture_snapshot_store),
) -> dict[str, Any]:
    """Return one stored architecture snapshot with its evidence."""

    snapshot = _read_stored_snapshot(store, repository_id, snapshot_id)

    return snapshot.to_dict()


@router.get(
    "/{repository_id}/snapshots/{snapshot_id}/details",
    summary="The evidence behind one recovered snapshot",
    response_description=(
        "Every element and relationship of the snapshot, joined with the "
        "recovery artifacts that identified it: discovery rules and "
        "artifacts, inventory files, resolution evidence, source findings, "
        "and any communication protocol the evidence establishes."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "That snapshot does not exist for that repository."
        }
    },
)
def read_snapshot_details(
    repository_id: str,
    snapshot_id: str,
    store: ArchitectureSnapshotStore = Depends(get_architecture_snapshot_store),
    checkouts: WorkspaceCheckouts = Depends(get_workspace_checkouts),
) -> dict[str, Any]:
    """Join a stored snapshot onto the artifacts the recovery stages wrote.

    The snapshot says what was concluded; this says why. It reads and never
    analyses, so a release whose clone is gone still returns its snapshot
    with the artifacts reported as absent rather than failing.
    """

    snapshot = _read_stored_snapshot(store, repository_id, snapshot_id)

    checkout = checkouts.find(repository_id, snapshot.release.release_id)

    return SnapshotDetails(checkout.parent if checkout else None).build(snapshot)


@router.get(
    "/{repository_id}/snapshots/{snapshot_id}/recovery",
    summary="How one release's architecture was recovered",
    response_description=(
        "One record per recovery stage - status, duration, counts and any "
        "reason it did not run - together with what the artifacts hold and "
        "which of them are still on disk."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "That snapshot does not exist for that repository."
        }
    },
)
def read_recovery_report(
    repository_id: str,
    snapshot_id: str,
    store: ArchitectureSnapshotStore = Depends(get_architecture_snapshot_store),
    checkouts: WorkspaceCheckouts = Depends(get_workspace_checkouts),
) -> dict[str, Any]:
    """Return the run record and the architecture it produced.

    `recorded` says whether this release has a run record at all. A release
    analysed before records existed reports `false` with no stages, which is
    a different fact from a pipeline that ran six stages and completed none.
    """

    snapshot = _read_stored_snapshot(store, repository_id, snapshot_id)
    checkout = checkouts.find(repository_id, snapshot.release.release_id)

    return build_report(snapshot, checkout.parent if checkout else None)


def _read_stored_snapshot(
    store: ArchitectureSnapshotStore, repository_id: str, snapshot_id: str
):
    """Read one snapshot, refusing with the status that fits the failure."""

    try:
        snapshot = store.read(repository_id, snapshot_id)
    except Exception as error:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Graph store unavailable: {error}",
        ) from error

    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No snapshot '{snapshot_id}' for repository '{repository_id}'.",
        )

    return snapshot


@router.delete("/{repository_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_repository(
    repository_id: str,
    service: RepositoryIngestionService = Depends(get_repository_ingestion_service),
    store: ArchitectureSnapshotStore = Depends(get_architecture_snapshot_store),
) -> None:
    """Remove an ingested repository from the machine and from the graph.

    The clone and its snapshot go together: a snapshot nobody can reach is a
    leak, and a clone whose history silently survived would be the same leak
    found later.
    """

    try:
        repository = service.get(repository_id)
    except RepositoryNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error

    # Purge before deleting the files. If the graph store is unreachable the
    # clone stays, so the caller can retry; the reverse order would delete the
    # only thing that could still be used to rebuild the history.
    try:
        _purge_snapshots(store, service, repository)
    except Exception as error:  # noqa: BLE001 - any driver failure is one outcome
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not remove the stored history of '{repository_id}': "
            f"{error}",
        ) from error

    try:
        service.remove(repository_id)
    except RepositoryNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error


def _purge_snapshots(
    store: ArchitectureSnapshotStore,
    service: RepositoryIngestionService,
    repository: IngestedRepository,
) -> None:
    """Delete the snapshots this clone is the last evidence for.

    One repository's history outlives any single clone. Removing the checkout
    of `v1.0.0` must not erase the snapshot of `v1.2.0`, which is still
    ingested and whose artifacts are still on disk - the two would then
    disagree about what has been analysed.

    So a clone removes its own revision's snapshots, and the whole history is
    dropped only when no clone of that repository remains.
    """

    key = repository.repository_key
    remaining = [
        other
        for other in service.list_ingested()
        if other.id != repository.id and other.repository_key == key
    ]

    if not remaining:
        store.delete_repository(key)
        return

    for summary in store.history(key):
        if summary.commit_sha == repository.commit:
            store.delete_snapshot(key, summary.snapshot_id)


def _inventory_after_ingest(
    repository: IngestedRepository,
    inventory_service: RepositoryInventoryService,
) -> tuple[
    RepositoryInventorySummaryResponse | None, RepositoryInventory | None, str | None
]:
    """Inventory a freshly cloned working tree.

    Returns the summary, the document itself and an error message. The document
    is returned because the next stage consumes it directly rather than reading
    it back from disk. Only `RepositoryInventoryError` is caught: that covers
    the expected failures (an unwritable output directory, a missing working
    tree). An unexpected exception is a defect and is deliberately allowed to
    surface.
    """

    try:
        path, inventory = inventory_service.run_for_ingested(repository)
    except RepositoryInventoryError as error:
        return None, None, str(error)

    return RepositoryInventorySummaryResponse.from_inventory(path, inventory), inventory, None


def _analysis_after_inventory(
    inventory: RepositoryInventory | None,
    repository: IngestedRepository,
    analysis_service: ManifestAnalysisService,
) -> tuple[
    ManifestAnalysisSummaryResponse | None,
    ManifestAnalysisReport | None,
    str | None,
]:
    """Analyze the manifests the inventory found.

    Analysis depends on the inventory, so when the inventory failed this stage
    is skipped and says so rather than reporting a misleadingly empty report.
    Returns the summary, the report itself and an error message.
    """

    if inventory is None:
        return None, None, "skipped: no repository inventory to analyze"

    try:
        path, report = analysis_service.run(
            inventory, repository.path, repository.path.parent
        )
    except ManifestAnalysisError as error:
        return None, None, str(error)

    return ManifestAnalysisSummaryResponse.from_report(path, report), report, None


def _discovery_after_analysis(
    inventory: RepositoryInventory | None,
    analysis: ManifestAnalysisReport | None,
    repository: IngestedRepository,
    discovery_service: ComponentDiscoveryService,
) -> tuple[
    ComponentDiscoverySummaryResponse | None,
    ComponentDiscoveryReport | None,
    str | None,
]:
    """Discover components from the inventory and the manifest analysis.

    Component discovery needs both upstream results, so it is skipped - with a
    reason - when either is missing, rather than reporting components derived from
    half the evidence. The report itself is returned because dependency
    resolution consumes it directly instead of reading it back from disk.
    """

    if inventory is None:
        return (
            None,
            None,
            "skipped: no repository inventory to derive components from",
        )

    if analysis is None:
        return None, None, "skipped: no manifest analysis to derive components from"

    try:
        path, report = discovery_service.run(
            inventory, analysis, repository.path.parent
        )
    except ComponentDiscoveryError as error:
        return None, None, str(error)

    return ComponentDiscoverySummaryResponse.from_report(path, report), report, None


def _dependencies_after_discovery(
    discovery: ComponentDiscoveryReport | None,
    analysis: ManifestAnalysisReport | None,
    repository: IngestedRepository,
    dependency_service: DependencyResolutionService,
) -> tuple[
    DependencyResolutionSummaryResponse | None,
    DependencyResolutionReport | None,
    str | None,
]:
    """Resolve relationships from the component discovery and analysis reports.

    Dependency resolution needs both upstream results, so it is skipped - with a
    reason - when either is missing. It runs after discovery because component
    IDs are the endpoints of every relationship. The report itself is returned
    because source code analysis consumes it directly.
    """

    if discovery is None:
        return (
            None,
            None,
            "skipped: no component discovery to derive dependencies from",
        )

    if analysis is None:
        return None, None, "skipped: no manifest analysis to derive dependencies from"

    try:
        path, report = dependency_service.run(
            discovery, analysis, repository.path.parent
        )
    except DependencyResolutionError as error:
        return None, None, str(error)

    return DependencyResolutionSummaryResponse.from_report(path, report), report, None


def _source_analysis_after_dependencies(
    inventory: RepositoryInventory | None,
    discovery: ComponentDiscoveryReport | None,
    dependencies: DependencyResolutionReport | None,
    repository: IngestedRepository,
    source_analysis_service: SourceCodeAnalysisService,
) -> tuple[
    SourceCodeAnalysisSummaryResponse | None,
    SourceCodeAnalysisReport | None,
    str | None,
]:
    """Analyze source code after the component and dependency reports exist.

    A source analysis failure does not stop the pipeline: graph construction
    runs with the source report absent and records an incomplete snapshot, so
    the missing evidence is visible instead of silently looking like a release
    with no source-level calls.
    """

    if inventory is None:
        return (
            None,
            None,
            "skipped: no repository inventory to analyze source code from",
        )

    if discovery is None:
        return None, None, "skipped: no component discovery to analyze source code from"

    if dependencies is None:
        return (
            None,
            None,
            "skipped: no dependency resolution to analyze source code from",
        )

    try:
        path, report = source_analysis_service.run(
            inventory,
            discovery,
            dependencies,
            repository.path,
            repository.path.parent,
        )
    except SourceCodeAnalysisError as error:
        return None, None, str(error)

    return SourceCodeAnalysisSummaryResponse.from_report(path, report), report, None


def _graph_after_source(
    repository: IngestedRepository,
    discovery: ComponentDiscoveryReport | None,
    dependencies: DependencyResolutionReport | None,
    source_analysis: SourceCodeAnalysisReport | None,
    graph_service: GraphConstructionService,
) -> tuple[GraphConstructionSummaryResponse | None, str | None]:
    """Build and persist one snapshot for the analyzed revision.

    The snapshot is written even when source evidence is missing, because an
    incomplete snapshot is a fact a consumer can read; a missing one is not.
    """

    if discovery is None:
        return None, "skipped: no component discovery to build a snapshot from"

    if dependencies is None:
        return None, "skipped: no dependency resolution to build a snapshot from"

    try:
        path, report = graph_service.run(
            release=release_from_ingested(repository),
            discovery=discovery,
            dependencies=dependencies,
            source=source_analysis,
            workspace=repository.path.parent,
        )
    except GraphConstructionError as error:
        return None, str(error)

    return GraphConstructionSummaryResponse.from_report(path, report), None


def _analyse(
    repository: IngestedRepository,
    inventory_service: RepositoryInventoryService,
    analysis_service: ManifestAnalysisService,
    discovery_service: ComponentDiscoveryService,
    dependency_service: DependencyResolutionService,
    source_analysis_service: SourceCodeAnalysisService,
    graph_service: GraphConstructionService,
) -> RecoveryResponse:
    """Run every recovery stage over a clone that has already succeeded.

    The clone has succeeded, so from here on nothing may report the ingest as
    failed: a downstream problem is surfaced in the body instead.

    Each stage is timed and recorded, and the record is written beside the
    artifacts it produced. That is what lets a screen say how the architecture
    was recovered rather than only that it was: a summary in a response is
    gone the moment the response is, and the difference between a stage that
    found nothing and one that never ran cannot be recovered from an artifact
    that does not exist.
    """

    started_at = now()
    records: list[StageRecord] = []
    artifacts = repository.path.parent

    with StageTimer(STAGE_BY_NAME["repository_inventory"]) as timer:
        inventory, inventory_document, inventory_error = _inventory_after_ingest(
            repository, inventory_service
        )
    records.append(
        timer.record(
            summary=_summary_of(inventory),
            error=inventory_error,
            report=inventory_document,
            artifact_directory=artifacts,
        )
    )

    with StageTimer(STAGE_BY_NAME["manifest_analysis"]) as timer:
        analysis, analysis_document, analysis_error = _analysis_after_inventory(
            inventory_document, repository, analysis_service
        )
    records.append(
        timer.record(
            summary=_summary_of(analysis),
            error=analysis_error,
            report=analysis_document,
            artifact_directory=artifacts,
        )
    )

    with StageTimer(STAGE_BY_NAME["component_discovery"]) as timer:
        discovery, discovery_document, discovery_error = _discovery_after_analysis(
            inventory_document, analysis_document, repository, discovery_service
        )
    records.append(
        timer.record(
            summary=_summary_of(discovery),
            error=discovery_error,
            report=discovery_document,
            artifact_directory=artifacts,
        )
    )

    with StageTimer(STAGE_BY_NAME["dependency_resolution"]) as timer:
        (
            dependencies,
            dependency_document,
            dependencies_error,
        ) = _dependencies_after_discovery(
            discovery_document, analysis_document, repository, dependency_service
        )
    records.append(
        timer.record(
            summary=_summary_of(dependencies),
            error=dependencies_error,
            report=dependency_document,
            artifact_directory=artifacts,
        )
    )

    with StageTimer(STAGE_BY_NAME["source_code_analysis"]) as timer:
        source_analysis, source_report, source_analysis_error = (
            _source_analysis_after_dependencies(
                inventory_document,
                discovery_document,
                dependency_document,
                repository,
                source_analysis_service,
            )
        )
    records.append(
        timer.record(
            summary=_summary_of(source_analysis),
            error=source_analysis_error,
            report=source_report,
            artifact_directory=artifacts,
        )
    )

    with StageTimer(STAGE_BY_NAME["graph_construction"]) as timer:
        graph, graph_error = _graph_after_source(
            repository, discovery_document, dependency_document, source_report, graph_service
        )
    records.append(
        timer.record(
            summary=_summary_of(graph),
            error=graph_error,
            artifact_directory=artifacts,
        )
    )

    _record_run(repository, records, started_at)

    return RecoveryResponse(
        **IngestedRepositoryResponse.model_validate(repository).model_dump(),
        inventory=inventory,
        inventory_error=inventory_error,
        manifest_analysis=analysis,
        manifest_analysis_error=analysis_error,
        component_discovery=discovery,
        component_discovery_error=discovery_error,
        dependency_resolution=dependencies,
        dependency_resolution_error=dependencies_error,
        source_code_analysis=source_analysis,
        source_code_analysis_error=source_analysis_error,
        graph_construction=graph,
        graph_construction_error=graph_error,
    )


def _summary_of(summary: object | None) -> dict | None:
    """The stage summary as a plain mapping, or nothing when it was skipped."""

    return summary.model_dump() if summary is not None else None


def _record_run(
    repository: IngestedRepository, records: list[StageRecord], started_at
) -> None:
    """Write this run's record beside the artifacts it produced.

    A failure to write it must not fail the recovery: the architecture is
    already stored, and losing the account of how it was built is a smaller
    loss than losing the build.
    """

    try:
        write_run(
            repository.path.parent,
            build_run(
                repository=repository,
                stages=records,
                started_at=started_at,
                finished_at=now(),
            ),
        )
    except OSError:
        pass


def _describe_git_failure(error: GitCommandError) -> str:
    """Reduce a git failure to the actionable line shown to the client."""

    message = error.stderr.strip()

    if not message:
        return "git command failed."

    # git reports the actionable cause on the last line of stderr.
    return message.splitlines()[-1].strip()
