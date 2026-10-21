"""Which configured snapshots the pipeline still has work for.

Author: Imadh Ifham
Date: 2026-10-21
Description:
    Cloning a revision costs minutes and replaces the checkout's directory,
    which is also where that snapshot's recovery artifacts live. Recovering a
    snapshot costs the same again in analysis. So the pipeline asks this
    service what is left before it starts, and a snapshot that is already
    cloned or already recovered is not touched.

    **The two questions are answered from the files a previous run left.** A
    checkout is a `metadata.json` beside a working tree; a recovery is a
    `recovery_run.json` whose graph construction completed, beside the
    snapshot that stage wrote. Anything less is reported as missing, because
    the alternative is skipping work on the strength of a directory name.
"""

from collections.abc import Iterable
from pathlib import Path

from app.components.architecture_recovery.graph_construction.writer import (
    GRAPH_CONSTRUCTION_DIRECTORY,
    GRAPH_CONSTRUCTION_FILE_NAME,
)
from app.components.architecture_recovery.recovery_run.models import (
    STATUS_COMPLETED,
    read_run,
)
from app.components.architecture_recovery.repository_ingestion.errors import (
    InvalidRepositorySource,
    RepositoryNotFound,
)
from app.components.architecture_recovery.repository_ingestion.service import (
    RepositoryIngestionService,
    build_repository_key,
)
from app.domain.repository import IngestedRepository
from app.domain.repository_configuration import RepositoryConfiguration

from .models import CloneState, RecoveryState, SnapshotStage, SnapshotState

GRAPH_CONSTRUCTION_STAGE = "graph_construction"


class PipelineStateService:
    """Reads what the workspace already holds for each configured snapshot."""

    def __init__(self, ingestion: RepositoryIngestionService) -> None:
        self._ingestion = ingestion

    def states(
        self, configurations: Iterable[RepositoryConfiguration]
    ) -> list[SnapshotState]:
        """Return one state per configuration, in the order given."""

        return [self.state(configuration) for configuration in configurations]

    def state(self, configuration: RepositoryConfiguration) -> SnapshotState:
        """What this configuration already has, and what it still needs."""

        try:
            workspace_id = self._ingestion.workspace_id_for(
                configuration.url,
                configuration.branch,
                configuration.release_tag,
            )
        except InvalidRepositorySource:
            # A configuration is validated before it is written, so this is a
            # store edited by hand. It has nothing on disk, which is what a
            # pending state says; refusing the whole list would hide the rest.
            return _pending(configuration, workspace_id="")

        try:
            checkout = self._ingestion.get(workspace_id)
        except RepositoryNotFound:
            return _pending(configuration, workspace_id)

        if not _is_checked_out(checkout):
            return _pending(configuration, workspace_id)

        clone = CloneState(
            id=checkout.id,
            commit=checkout.commit,
            branch=checkout.branch,
            release_tag=checkout.release_tag,
            ingested_at=checkout.ingested_at,
        )
        recovery = _recovery_state(checkout.path.parent)

        return SnapshotState(
            configuration_id=configuration.id,
            url=configuration.url,
            branch=configuration.branch,
            release_tag=configuration.release_tag,
            workspace_id=workspace_id,
            stage=SnapshotStage.RECOVERED if recovery else SnapshotStage.CLONED,
            repository_id=build_repository_key(configuration.url),
            clone=clone,
            recovery=recovery,
        )


def _pending(configuration: RepositoryConfiguration, workspace_id: str) -> SnapshotState:
    return SnapshotState(
        configuration_id=configuration.id,
        url=configuration.url,
        branch=configuration.branch,
        release_tag=configuration.release_tag,
        workspace_id=workspace_id,
        stage=SnapshotStage.PENDING,
        repository_id=build_repository_key(configuration.url),
    )


def _is_checked_out(checkout: IngestedRepository) -> bool:
    """Whether the record's working tree is actually there.

    A removal that stopped between the tree and the record leaves a metadata
    file describing nothing. Recovering that would fail at the first stage, so
    it is reported as needing a clone.
    """

    return checkout.path.is_dir()


def _recovery_state(directory: Path) -> RecoveryState | None:
    """The recovery of this checkout, when one finished and is still on disk.

    Both halves are required. The run record says a graph construction
    completed; the snapshot file says the architecture it produced is still
    there. A record without its artifact is a recovery that was deleted, and
    skipping it would leave the pipeline with nothing to validate.
    """

    run = read_run(directory)

    if run is None or run.get("status") != STATUS_COMPLETED:
        return None

    stage = _stage(run, GRAPH_CONSTRUCTION_STAGE)

    if stage is None or stage.get("status") != STATUS_COMPLETED:
        return None

    if not _snapshot_written(directory):
        return None

    counts = stage.get("counts") or {}

    return RecoveryState(
        release_id=str(run.get("release_id") or ""),
        commit_sha=str(run.get("commit_sha") or ""),
        finished_at=run.get("finished_at"),
        duration_ms=run.get("duration_ms"),
        element_count=_count(counts, "element_count"),
        relationship_count=_count(counts, "relationship_count"),
    )


def _stage(run: dict, name: str) -> dict | None:
    for stage in run.get("stages") or []:
        if isinstance(stage, dict) and stage.get("name") == name:
            return stage

    return None


def _snapshot_written(directory: Path) -> bool:
    """Whether graph construction's snapshot is under this checkout.

    Looked for at the one path that stage writes to, rather than by walking
    the tree: a clone holds tens of thousands of source files, and a search
    for a name across them costs more than reading the record.
    """

    graph_directory = directory / GRAPH_CONSTRUCTION_DIRECTORY

    if not graph_directory.is_dir():
        return False

    return any(graph_directory.glob(f"*/{GRAPH_CONSTRUCTION_FILE_NAME}"))


def _count(counts: dict, key: str) -> int | None:
    value = counts.get(key)

    return value if isinstance(value, int) and not isinstance(value, bool) else None


__all__ = ["GRAPH_CONSTRUCTION_STAGE", "PipelineStateService"]
