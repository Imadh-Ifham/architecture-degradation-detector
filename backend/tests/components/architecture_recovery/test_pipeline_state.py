"""What the pipeline believes is already done, and why it may not be.

The state decides whether a press of Recover clones a revision again and
whether it analyses one again. Re-cloning replaces the checkout's directory,
which is where the snapshot's recovery artifacts live, so a wrong `recovered`
is cheap and a wrong `pending` is destructive. These tests pin the difference
between "a directory is there" and "a recovery finished and its architecture
is still on disk".
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.components.architecture_recovery.pipeline_state import (
    PipelineStateService,
    SnapshotStage,
)
from app.components.architecture_recovery.repository_ingestion.service import (
    METADATA_FILE_NAME,
    SOURCE_DIRECTORY_NAME,
    RepositoryIngestionService,
    build_repository_key,
    build_revision_repository_id,
)
from app.domain.repository import IngestedRepository
from app.domain.repository_configuration import (
    RepositoryConfiguration,
    configuration_id_for,
)

URL = "https://example.com/team/repo.git"
BRANCH = "main"
RELEASE = "v1.0.0"
GRAPH_DIRECTORY = "graph_construction"
GRAPH_FILE_NAME = "architecture_graph_construction.json"


class UnusedGit:
    """Stands in for the git client: nothing here clones."""


def configuration() -> RepositoryConfiguration:
    return RepositoryConfiguration(
        id=configuration_id_for(URL, BRANCH, RELEASE),
        url=URL,
        branch=BRANCH,
        release_tag=RELEASE,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )


@pytest.fixture
def service(tmp_path: Path) -> PipelineStateService:
    return PipelineStateService(
        RepositoryIngestionService(git_client=UnusedGit(), root=tmp_path)
    )


def checkout(root: Path) -> Path:
    """Write the metadata and working tree an ingestion of this snapshot leaves."""

    workspace_id = build_revision_repository_id(URL, RELEASE)
    directory = root / workspace_id
    (directory / SOURCE_DIRECTORY_NAME).mkdir(parents=True)

    record = IngestedRepository(
        id=workspace_id,
        url=URL,
        branch=BRANCH,
        commit="a" * 40,
        path=directory / SOURCE_DIRECTORY_NAME,
        ingested_at=datetime(2025, 1, 2, tzinfo=UTC),
        repository_id=build_repository_key(URL),
        release_tag=RELEASE,
        revision=RELEASE,
    )
    (directory / METADATA_FILE_NAME).write_text(
        json.dumps(record.to_metadata()), encoding="utf-8"
    )

    return directory


def recovery(
    directory: Path,
    *,
    run_status: str = "completed",
    graph_status: str = "completed",
    snapshot: bool = True,
) -> None:
    """Write the record of a recovery, and the snapshot it produced."""

    document = {
        "status": run_status,
        "release_id": RELEASE,
        "commit_sha": "a" * 40,
        "finished_at": "2025-01-03T00:00:00+00:00",
        "duration_ms": 1234,
        "stages": [
            {"name": "component_discovery", "status": "completed", "counts": {}},
            {
                "name": "graph_construction",
                "status": graph_status,
                "counts": {"element_count": 3, "relationship_count": 2},
            },
        ],
    }

    (directory / "recovery_run.json").write_text(json.dumps(document), encoding="utf-8")

    if snapshot:
        written = directory / GRAPH_DIRECTORY / "snapshot-abc123"
        written.mkdir(parents=True, exist_ok=True)
        (written / GRAPH_FILE_NAME).write_text("{}", encoding="utf-8")


def test_a_snapshot_never_cloned_needs_both_halves(
    service: PipelineStateService,
) -> None:
    state = service.state(configuration())

    assert state.stage is SnapshotStage.PENDING
    assert state.needs_clone is True
    assert state.needs_recovery is True
    assert state.clone is None
    assert state.recovery is None


def test_a_clone_without_a_recovery_needs_only_recovery(
    service: PipelineStateService, tmp_path: Path
) -> None:
    checkout(tmp_path)

    state = service.state(configuration())

    assert state.stage is SnapshotStage.CLONED
    assert state.needs_clone is False
    assert state.needs_recovery is True
    assert state.clone is not None
    assert state.clone.commit == "a" * 40
    assert state.recovery is None


def test_a_recovery_that_finished_is_recovered_with_its_counts(
    service: PipelineStateService, tmp_path: Path
) -> None:
    recovery(checkout(tmp_path))

    state = service.state(configuration())

    assert state.stage is SnapshotStage.RECOVERED
    assert state.needs_clone is False
    assert state.needs_recovery is False
    assert state.recovery is not None
    assert state.recovery.element_count == 3
    assert state.recovery.relationship_count == 2
    assert state.recovery.release_id == RELEASE


def test_a_run_record_without_its_snapshot_is_not_recovered(
    service: PipelineStateService, tmp_path: Path
) -> None:
    """A deleted artifact means the work is missing, whatever the record says."""

    recovery(checkout(tmp_path), snapshot=False)

    state = service.state(configuration())

    assert state.stage is SnapshotStage.CLONED
    assert state.needs_recovery is True


def test_a_run_that_did_not_finish_is_not_recovered(
    service: PipelineStateService, tmp_path: Path
) -> None:
    recovery(checkout(tmp_path), run_status="failed")

    assert service.state(configuration()).stage is SnapshotStage.CLONED


def test_a_failed_graph_construction_is_not_recovered(
    service: PipelineStateService, tmp_path: Path
) -> None:
    """The snapshot file may exist from an earlier attempt; the stage failed."""

    recovery(checkout(tmp_path), graph_status="failed")

    assert service.state(configuration()).stage is SnapshotStage.CLONED


def test_metadata_without_a_working_tree_is_pending(
    service: PipelineStateService, tmp_path: Path
) -> None:
    """A removal that stopped halfway leaves a record describing nothing."""

    directory = checkout(tmp_path)
    (directory / SOURCE_DIRECTORY_NAME).rmdir()

    state = service.state(configuration())

    assert state.stage is SnapshotStage.PENDING
    assert state.needs_clone is True


def test_the_workspace_id_is_the_one_ingestion_writes(
    service: PipelineStateService,
) -> None:
    """The state may not answer with an id ingestion would never produce."""

    assert service.state(configuration()).workspace_id == build_revision_repository_id(
        URL, RELEASE
    )
