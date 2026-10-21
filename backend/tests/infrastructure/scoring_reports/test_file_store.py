# Tests for the file store that reads C4's saved runs: manifests and reports found per run
# folder, unreadable files left out, run ids that could leave the root refused.

from pathlib import Path

from app.infrastructure.scoring_reports import ScoringReportFileStore
from tests.components.degradation_scoring.saved_runs import save_run


def test_runs_returns_every_manifest(tmp_path: Path) -> None:
    save_run(tmp_path, "run-a")
    save_run(tmp_path, "run-b", system_id="online-boutique")

    runs = ScoringReportFileStore(tmp_path).runs()

    assert sorted(str(run["run_id"]) for run in runs) == ["run-a", "run-b"]


def test_reports_returns_the_saved_document(tmp_path: Path) -> None:
    saved = save_run(tmp_path, "run-a")

    assert ScoringReportFileStore(tmp_path).reports("run-a") == [saved]
    assert ScoringReportFileStore(tmp_path).reports("missing") == []


def test_same_run_id_in_two_systems_returns_both(tmp_path: Path) -> None:
    save_run(tmp_path, "run-a")
    save_run(tmp_path, "run-a", system_id="online-boutique")

    reports = ScoringReportFileStore(tmp_path).reports("run-a")

    assert sorted(str(r["system_id"]) for r in reports) == ["c4-fixture-shop", "online-boutique"]


def test_unreadable_files_are_left_out(tmp_path: Path) -> None:
    save_run(tmp_path, "good")
    broken = tmp_path / "c4-fixture-shop" / "broken"
    broken.mkdir()
    (broken / "c4_run_manifest.json").write_text("{not json", encoding="utf-8")
    (broken / "c4_report.json").write_text("[1, 2]", encoding="utf-8")
    store = ScoringReportFileStore(tmp_path)

    assert [run["run_id"] for run in store.runs()] == ["good"]
    assert store.reports("broken") == []


def test_run_ids_that_could_leave_the_root_are_refused(tmp_path: Path) -> None:
    save_run(tmp_path, "run-a")
    store = ScoringReportFileStore(tmp_path)

    for run_id in ["..", "../c4-fixture-shop/run-a", "run-a/../run-a", ".hidden", ""]:
        assert store.reports(run_id) == []


def test_missing_root_has_no_runs(tmp_path: Path) -> None:
    store = ScoringReportFileStore(tmp_path / "nothing-yet")

    assert store.runs() == []
    assert store.reports("run-a") == []


def test_files_returns_the_bytes_of_every_run_folder(tmp_path: Path) -> None:
    save_run(tmp_path, "run-a")
    save_run(tmp_path, "run-a", system_id="online-boutique")
    for system in ("c4-fixture-shop", "online-boutique"):
        (tmp_path / system / "run-a" / "c4_report.html").write_text(system, encoding="utf-8")

    store = ScoringReportFileStore(tmp_path)

    assert store.files("run-a", "c4_report.html") == [b"c4-fixture-shop", b"online-boutique"]
    assert store.files("run-a", "missing.json") == []
    assert store.files("../run-a", "c4_report.html") == []
    assert store.files("run-a", "../c4_report.html") == []
    assert ScoringReportFileStore(tmp_path / "absent").files("run-a", "c4_report.html") == []
