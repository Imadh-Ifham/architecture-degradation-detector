"""Recovery run record tests.

Description:
    The record is the difference between a page that says a stage found nothing
    and one that says it never ran. These check the three outcomes the pipeline
    can produce, and that a run is only "completed" when every stage ran.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.components.architecture_recovery.recovery_run import (
    RECOVERY_STAGES,
    StageRecord,
    StageTimer,
    build_run,
    read_run,
    write_run,
)

STARTED = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
FINISHED = STARTED + timedelta(milliseconds=2500)


class FakeRepository:
    """The fields the record keeps about a release."""

    id = "microservices-demo-v0.9.0"
    repository_key = "microservices-demo-58a841308994"
    release_id = "v0.9.0"
    url = "https://example.com/team/repo.git"
    branch = "release/v0.9.0"
    commit = "a" * 40


def staged(stage: str) -> StageTimer:
    timer = StageTimer(next(item for item in RECOVERY_STAGES if item.name == stage))
    timer.duration_ms = 12
    return timer


class TestStageStatus:
    def test_a_summary_with_no_error_is_completed(self, tmp_path: Path) -> None:
        record = staged("repository_inventory").record(
            summary={"path": "x/inventory.json", "file_count": 4, "truncated": False},
            error=None,
            artifact_directory=tmp_path,
        )

        assert record.status == "completed"
        # Paths and non-numeric fields are not counts.
        assert record.counts == {"file_count": 4}

    def test_a_skip_is_read_from_the_reason_the_handler_gave(
        self, tmp_path: Path
    ) -> None:
        record = staged("manifest_analysis").record(
            summary=None,
            error="skipped: no repository inventory to analyze",
            artifact_directory=tmp_path,
        )

        assert record.status == "skipped"
        assert record.note == "no repository inventory to analyze"
        assert record.counts == {}

    def test_a_failure_keeps_its_message(self, tmp_path: Path) -> None:
        record = staged("component_discovery").record(
            summary=None,
            error="discovery workspace is not writable",
            artifact_directory=tmp_path,
        )

        assert record.status == "failed"
        assert record.note == "discovery workspace is not writable"

    def test_warnings_come_from_the_stage_report(self, tmp_path: Path) -> None:
        class Report:
            warnings = ("a manifest could not be parsed",)

        record = staged("manifest_analysis").record(
            summary={"analyzed_count": 1},
            error=None,
            report=Report(),
            artifact_directory=tmp_path,
        )

        assert record.warnings == ["a manifest could not be parsed"]

    def test_an_artifact_is_found_one_directory_down(self, tmp_path: Path) -> None:
        """Graph construction writes inside a directory named for the snapshot."""

        nested = tmp_path / "graph_construction" / "snapshot_1"
        nested.mkdir(parents=True)
        (nested / "architecture_graph_construction.json").write_text("{}", encoding="utf-8")

        record = staged("graph_construction").record(
            summary={"element_count": 2},
            error=None,
            artifact_directory=tmp_path,
        )

        assert record.artifact_present is True

    def test_an_absent_artifact_is_recorded_as_absent(self, tmp_path: Path) -> None:
        record = staged("source_code_analysis").record(
            summary={"finding_count": 0},
            error=None,
            artifact_directory=tmp_path,
        )

        assert record.artifact_present is False


class TestRunStatus:
    def test_a_run_with_every_stage_is_complete(self) -> None:
        document = build_run(
            repository=FakeRepository(),
            stages=[
                _record(stage.name, "completed")
                for stage in RECOVERY_STAGES
            ],
            started_at=STARTED,
            finished_at=FINISHED,
        )

        assert document["status"] == "completed"
        assert document["stage_count"] == 6
        assert document["duration_ms"] == 2500
        assert document["release_id"] == "v0.9.0"
        assert document["repository_id"] == "microservices-demo-58a841308994"

    def test_a_skipped_stage_makes_the_run_incomplete(self) -> None:
        document = build_run(
            repository=FakeRepository(),
            stages=[
                _record(RECOVERY_STAGES[0].name, "completed"),
                _record(RECOVERY_STAGES[1].name, "skipped"),
            ],
            started_at=STARTED,
            finished_at=FINISHED,
        )

        assert document["status"] == "incomplete"

    def test_a_failed_stage_makes_the_run_failed(self) -> None:
        document = build_run(
            repository=FakeRepository(),
            stages=[_record(RECOVERY_STAGES[0].name, "failed")],
            started_at=STARTED,
            finished_at=FINISHED,
        )

        assert document["status"] == "failed"


class TestRoundTrip:
    def test_a_written_run_reads_back_unchanged(self, tmp_path: Path) -> None:
        document = build_run(
            repository=FakeRepository(),
            stages=[_record(RECOVERY_STAGES[0].name, "completed")],
            started_at=STARTED,
            finished_at=FINISHED,
        )

        write_run(tmp_path, document)

        assert read_run(tmp_path) == json.loads(
            (tmp_path / "recovery_run.json").read_text(encoding="utf-8")
        )

    def test_a_directory_without_a_record_reads_as_none(self, tmp_path: Path) -> None:
        assert read_run(tmp_path) is None
        assert read_run(None) is None

    def test_a_corrupt_record_reads_as_none(self, tmp_path: Path) -> None:
        (tmp_path / "recovery_run.json").write_text("{oops", encoding="utf-8")

        assert read_run(tmp_path) is None


def _record(name: str, status: str) -> StageRecord:
    return StageRecord(
        name=name,
        order=1,
        status=status,
        duration_ms=10,
    )
