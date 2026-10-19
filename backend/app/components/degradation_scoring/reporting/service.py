# Reporting service: writes one run's files  into its own output folder:
# c4_report.json, c4_report.html, c4_quarantine.json and c4_run_manifest.json.

import datetime as dt
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.components.degradation_scoring.reporting.errors import OutputExistsError
from app.components.degradation_scoring.reporting.manifest import build_manifest
from app.components.degradation_scoring.reporting.models import ReportView, RunOutputs
from app.components.degradation_scoring.reporting.writer import (
    quarantine_json,
    render_html,
    report_json,
    to_json,
)
from app.domain.severity_report import SeverityReportV1

REPORT_JSON = "c4_report.json"
REPORT_HTML = "c4_report.html"
QUARANTINE = "c4_quarantine.json"
MANIFEST = "c4_run_manifest.json"


class ReportingService:
    # Writes the severity report and the run manifest for one run; write() is the entry method.

    def write(
        self,
        report: SeverityReportV1,
        view: ReportView,
        facts: Mapping[str, Any],
        directory: Path,
        *,
        created_at: dt.datetime | None = None,
    ) -> RunOutputs:
        # refuses a folder that already holds files, so one run never overwrites another
        if directory.exists() and any(directory.iterdir()):
            raise OutputExistsError(f"{directory} already holds a run's files")
        files = {
            REPORT_JSON: report_json(report).encode("utf-8"),
            REPORT_HTML: render_html(report, view).encode("utf-8"),
            QUARANTINE: quarantine_json(report).encode("utf-8"),
        }
        manifest = build_manifest(facts, files, created_at or dt.datetime.now(dt.UTC))
        files[MANIFEST] = to_json(manifest).encode("utf-8")
        directory.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            (directory / name).write_bytes(data)
        return RunOutputs(
            directory=directory,
            report_json=directory / REPORT_JSON,
            report_html=directory / REPORT_HTML,
            manifest=directory / MANIFEST,
            quarantine=directory / QUARANTINE,
        )
