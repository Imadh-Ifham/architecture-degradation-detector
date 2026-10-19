# Report writer : the JSON report, checked against SeverityReportV1, the
# static HTML report (Jinja2, no JavaScript) and the quarantine file.

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.components.degradation_scoring.reporting.errors import ReportSchemaError
from app.components.degradation_scoring.reporting.models import ReportView
from app.domain.severity_report import SCHEMA_VERSION, DataProvenance, Dimension, SeverityReportV1

TEMPLATES = Path(__file__).parent / "templates"

DIMENSION_LABELS = {
    Dimension.BLAST_RADIUS: "Blast radius",
    Dimension.HOTSPOT: "Hotspot",
    Dimension.ADR_VIOLATION: "ADR violation",
    Dimension.PERSISTENCE: "Persistence",
}

BANNERS = {
    DataProvenance.FIXTURE: (
        "FIXTURE DATA: hand-designed test input. These numbers are not results."
    ),
    DataProvenance.FIXTURE_EVENTS_LIVE_HISTORY: (
        "FIXTURE EVENTS: the events and graph are hand-made; only the commit history is real. "
        "These numbers are not findings."
    ),
}


def to_json(value: Any) -> str:
    # stable text: model order, 2-space indent, trailing newline
    return json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def report_json(report: SeverityReportV1) -> str:
    # the report as JSON, read back through SeverityReportV1 before it is returned
    text = to_json(report.model_dump(mode="json"))
    if SeverityReportV1.model_validate_json(text) != report:
        raise ReportSchemaError("the report does not round-trip through SeverityReportV1")
    if report.schema_version != SCHEMA_VERSION:
        raise ReportSchemaError(
            f"report schema {report.schema_version}, contract is {SCHEMA_VERSION}"
        )
    return text


def quarantine_json(report: SeverityReportV1) -> str:
    # every event left out of the ranking, and why
    return to_json(
        {
            "run_id": report.run_id,
            "system_id": report.system_id,
            "release_id": report.release_id,
            "quarantined": [item.model_dump(mode="json") for item in report.quarantined],
            "skipped": [item.model_dump(mode="json") for item in report.skipped],
        }
    )


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=True,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["pct"] = lambda value: f"{100 * value:.1f}%"
    env.filters["num"] = lambda value: f"{value:.4g}" if isinstance(value, float) else value
    return env


def render_html(report: SeverityReportV1, view: ReportView) -> str:
    # one summary header, then one card per ranked event
    return (
        _environment()
        .get_template("report.html.j2")
        .render(
            report=report,
            view=view,
            labels=DIMENSION_LABELS,
            dimensions=list(Dimension),
            banner=BANNERS.get(report.data_provenance),
        )
    )
