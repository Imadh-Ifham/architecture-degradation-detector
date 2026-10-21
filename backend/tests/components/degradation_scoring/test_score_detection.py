# Tests for DegradationScoringService.score_detection: a detection run's hand-over ranked as
# score-<run>, saved once (a repeat returns the saved run), labelled live, and a missing
# hand-over refused.

import json
from pathlib import Path

import pytest

from app.components.degradation_scoring import DegradationScoringService
from app.components.degradation_scoring.errors import HandoverNotFoundError
from app.domain.severity_report import DataProvenance
from app.infrastructure.scoring_reports import DetectionHandoverFiles, ScoringReportFileStore
from tests.components.degradation_scoring.support import (
    FakeRunRepository,
    default_config,
    load_fixture,
)

SYSTEM = "c4-fixture-shop"


def write_handover(root: Path, run_id: str, events: object) -> None:
    folder = root / SYSTEM / run_id
    folder.mkdir(parents=True)
    (folder / "events.json").write_text(json.dumps(events), encoding="utf-8")
    package = load_fixture("graphs/fixture_release_package.v1.5.0.json")
    (folder / "release_package.json").write_text(json.dumps(package), encoding="utf-8")


def service(tmp_path: Path, runs: FakeRunRepository) -> DegradationScoringService:
    config = default_config().model_copy(update={"outputs_root": tmp_path / "scoring"})
    return DegradationScoringService(
        config,
        run_repository=runs,
        saved_reports=ScoringReportFileStore(tmp_path / "scoring"),
        detection_handover=DetectionHandoverFiles(tmp_path / "degradation"),
    )


def test_a_detection_run_is_ranked_and_saved_as_live(tmp_path: Path) -> None:
    write_handover(tmp_path / "degradation", "RUN-a", load_fixture("events/fixture_events.v1.json"))
    runs = FakeRunRepository()

    saved = service(tmp_path, runs).score_detection(SYSTEM, "RUN-a")

    assert saved.run_id == "score-RUN-a"
    assert saved.system_id == SYSTEM
    assert saved.data_provenance is DataProvenance.LIVE
    assert saved.counts.ranked > 0
    assert (tmp_path / "scoring" / SYSTEM / "score-RUN-a" / "c4_report.json").is_file()
    assert len(runs.saved) == 1


def test_a_run_already_scored_is_returned_not_scored_again(tmp_path: Path) -> None:
    write_handover(tmp_path / "degradation", "RUN-a", load_fixture("events/fixture_events.v1.json"))
    runs = FakeRunRepository()
    first = service(tmp_path, runs).score_detection(SYSTEM, "RUN-a")

    again = service(tmp_path, runs).score_detection(SYSTEM, "RUN-a")

    assert again == first
    assert len(runs.saved) == 1


def test_a_run_with_no_events_gives_an_empty_ranking(tmp_path: Path) -> None:
    write_handover(tmp_path / "degradation", "RUN-empty", [])

    saved = service(tmp_path, FakeRunRepository()).score_detection(SYSTEM, "RUN-empty")

    assert (saved.counts.payloads, saved.counts.ranked) == (0, 0)


def test_a_missing_handover_is_refused(tmp_path: Path) -> None:
    with pytest.raises(HandoverNotFoundError, match="RUN-missing"):
        service(tmp_path, FakeRunRepository()).score_detection(SYSTEM, "RUN-missing")


def test_without_a_handover_source_nothing_can_be_scored(tmp_path: Path) -> None:
    config = default_config().model_copy(update={"outputs_root": tmp_path})
    bare = DegradationScoringService(config, saved_reports=ScoringReportFileStore(tmp_path))

    with pytest.raises(HandoverNotFoundError):
        bare.score_detection(SYSTEM, "RUN-a")
