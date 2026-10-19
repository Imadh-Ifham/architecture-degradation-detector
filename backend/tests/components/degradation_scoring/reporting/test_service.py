# Tests for the reporting service (C4-T20): one run's four files, the manifest's hashes of the
# other files, and no overwriting of an earlier run.

import datetime as dt
import json
from pathlib import Path

import pytest

from app.components.degradation_scoring import reporting
from app.components.degradation_scoring.reporting.errors import OutputExistsError
from app.components.degradation_scoring.reporting.manifest import file_hash
from app.components.degradation_scoring.reporting.service import ReportingService
from tests.components.degradation_scoring.support import sample_report, sample_view

CREATED = dt.datetime(2026, 10, 18, 12, 0, tzinfo=dt.UTC)


def test_package_exports_only_the_service() -> None:
    assert reporting.__all__ == ["ReportingService"]
    assert reporting.ReportingService is ReportingService


def test_write_creates_the_four_run_files(tmp_path: Path) -> None:
    directory = tmp_path / "unit-system" / "unit-run"
    outputs = ReportingService().write(
        sample_report(), sample_view(), {"run_id": "unit-run"}, directory, created_at=CREATED
    )

    assert outputs.directory == directory
    assert sorted(p.name for p in directory.iterdir()) == [
        "c4_quarantine.json",
        "c4_report.html",
        "c4_report.json",
        "c4_run_manifest.json",
    ]
    assert json.loads(outputs.report_json.read_text(encoding="utf-8"))["run_id"] == "unit-run"
    assert "<!doctype html>" in outputs.report_html.read_text(encoding="utf-8")
    assert json.loads(outputs.quarantine.read_text(encoding="utf-8"))["skipped"]


def test_manifest_hashes_the_other_files(tmp_path: Path) -> None:
    outputs = ReportingService().write(
        sample_report(), sample_view(), {"run_id": "unit-run"}, tmp_path / "run", created_at=CREATED
    )
    manifest = json.loads(outputs.manifest.read_text(encoding="utf-8"))

    assert manifest["run_id"] == "unit-run"
    assert manifest["created_at"] == "2026-10-18T12:00:00+00:00"
    for path in (outputs.report_json, outputs.report_html, outputs.quarantine):
        assert manifest["outputs"][path.name] == file_hash(path.read_bytes())


def test_files_use_unix_line_endings(tmp_path: Path) -> None:
    outputs = ReportingService().write(
        sample_report(), sample_view(), {"run_id": "unit-run"}, tmp_path / "run", created_at=CREATED
    )

    assert b"\r\n" not in outputs.report_json.read_bytes()
    assert b"\r\n" not in outputs.report_html.read_bytes()


def test_an_earlier_run_is_never_overwritten(tmp_path: Path) -> None:
    service = ReportingService()
    service.write(sample_report(), sample_view(), {}, tmp_path / "run", created_at=CREATED)
    before = (tmp_path / "run" / "c4_report.json").read_bytes()

    with pytest.raises(OutputExistsError):
        service.write(
            sample_report(ahp_cr=0.05), sample_view(), {}, tmp_path / "run", created_at=CREATED
        )
    assert (tmp_path / "run" / "c4_report.json").read_bytes() == before


def test_an_empty_existing_folder_is_used(tmp_path: Path) -> None:
    (tmp_path / "run").mkdir()
    outputs = ReportingService().write(sample_report(), sample_view(), {}, tmp_path / "run")

    assert outputs.manifest.exists()
