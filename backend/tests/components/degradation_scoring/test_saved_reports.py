# Tests for the read-side query methods DegradationScoringService.runs() / report(): newest
# first, manifests that do not fit left out, contract checked, ambiguous ids refused.

from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from app.components.degradation_scoring import DegradationScoringService
from app.components.degradation_scoring.errors import AmbiguousRunError, SavedReportError
from app.components.degradation_scoring.ports import SavedReportSource
from app.domain.severity_report import DataProvenance, SeverityReportV1
from app.infrastructure.scoring_reports import ScoringReportFileStore
from tests.components.degradation_scoring.saved_runs import golden_report, save_run
from tests.components.degradation_scoring.support import default_config


class FakeSource:
    # an in-memory SavedReportSource
    def __init__(
        self,
        runs: Sequence[Mapping[str, object]] = (),
        reports: Sequence[Mapping[str, object]] = (),
    ) -> None:
        self._runs, self._reports = list(runs), list(reports)

    def runs(self) -> Sequence[Mapping[str, object]]:
        return self._runs

    def reports(self, run_id: str) -> Sequence[Mapping[str, object]]:
        return [r for r in self._reports if r["run_id"] == run_id]

    def files(self, run_id: str, name: str) -> Sequence[bytes]:
        return [f"{run_id}/{name}".encode() for r in self._reports if r["run_id"] == run_id]


def service(source: SavedReportSource) -> DegradationScoringService:
    return DegradationScoringService(default_config(), saved_reports=source)


def test_runs_come_newest_first_with_their_counts(tmp_path: Path) -> None:
    save_run(tmp_path, "older", created_at="2026-10-18T10:00:00+00:00")
    save_run(tmp_path, "newer", created_at="2026-10-19T10:00:00+00:00")

    runs = service(ScoringReportFileStore(tmp_path)).runs()

    assert [run.run_id for run in runs] == ["newer", "older"]
    assert runs[0].data_provenance is DataProvenance.FIXTURE
    assert (runs[0].counts.ranked, runs[0].counts.skipped, runs[0].counts.quarantined) == (9, 4, 4)
    assert runs[0].resolution_rate == 0.9


def test_a_manifest_that_does_not_fit_is_left_out() -> None:
    good = {
        "run_id": "good",
        "system_id": "s",
        "release_id": "v1",
        "data_provenance": "live",
        "active_dimensions": ["blast_radius"],
        "counts": {"payloads": 1, "ranked": 1, "skipped": 0, "quarantined": 0},
        "resolution_rate": 1.0,
        "created_at": "2026-10-19T10:00:00+00:00",
    }
    bad = good | {"run_id": "bad", "data_provenance": "made-up"}

    assert [run.run_id for run in service(FakeSource(runs=[good, bad])).runs()] == ["good"]


def test_report_is_the_saved_report_checked_against_the_contract(tmp_path: Path) -> None:
    saved = save_run(tmp_path, "run-a")

    report = service(ScoringReportFileStore(tmp_path)).report("run-a")

    assert report == SeverityReportV1.model_validate(saved)
    assert report is not None
    assert [record.rank for record in report.records] == list(range(1, 10))


def test_unknown_run_is_none() -> None:
    assert service(FakeSource()).report("missing") is None


def test_ambiguous_run_id_raises() -> None:
    reports = [golden_report(), golden_report() | {"system_id": "other"}]

    with pytest.raises(AmbiguousRunError, match="several systems"):
        service(FakeSource(reports=reports)).report("golden")


def test_report_that_breaks_the_contract_raises() -> None:
    broken = golden_report() | {"resolution_rate": 2.0}

    with pytest.raises(SavedReportError, match="breaks SeverityReportV1"):
        service(FakeSource(reports=[broken])).report("golden")


def test_no_source_configured_raises() -> None:
    with pytest.raises(SavedReportError, match="no saved report source"):
        DegradationScoringService(default_config()).runs()


def test_run_file_returns_an_allowed_file(tmp_path: Path) -> None:
    save_run(tmp_path, "run-a")
    (tmp_path / "c4-fixture-shop" / "run-a" / "c4_report.html").write_text("<html>", "utf-8")
    reader = service(ScoringReportFileStore(tmp_path))

    assert reader.run_file("run-a", "c4_report.html") == b"<html>"
    assert reader.run_file("run-a", "c4_quarantine.json") is None
    assert reader.run_file("missing", "c4_report.html") is None


def test_run_file_refuses_names_outside_the_run_files(tmp_path: Path) -> None:
    save_run(tmp_path, "run-a")

    assert service(ScoringReportFileStore(tmp_path)).run_file("run-a", "logs") is None


def test_run_file_with_an_id_in_two_systems_is_ambiguous() -> None:
    reports = [{"run_id": "run-a"}, {"run_id": "run-a"}]

    with pytest.raises(AmbiguousRunError):
        service(FakeSource(reports=reports)).run_file("run-a", "c4_report.json")
