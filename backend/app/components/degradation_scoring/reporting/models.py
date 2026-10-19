# Data structures of the reporting subcomponent: what the HTML shows beyond the JSON report,
# and where one run's files were written.

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.domain.severity_report import Dimension


class EventNotes(BaseModel):
    # one ranked event's extra facts for its HTML card: graph nodes, flag badges, PS metric

    model_config = ConfigDict(frozen=True)

    nodes: list[str]
    flags: list[str]
    growth_metric: str | None = None
    adr_id: str | None = None


class ReportView(BaseModel):
    # run facts for the HTML header that SeverityReportV1 does not carry

    model_config = ConfigDict(frozen=True)

    payloads: int
    topsis_mode: str
    weights_elicited_by: str
    ahp_lambda_max: float
    elicited_weights: dict[Dimension, float]
    weights: dict[Dimension, float]
    hotspot_inactive_reason: str | None = None
    adr_inactive_reason: str | None = None
    unmapped_line_share: float | None = None
    path_mapping: str | None = None
    notes: dict[str, EventNotes]


class RunOutputs(BaseModel):
    # the files of one run (CLAUDE.md §6)

    model_config = ConfigDict(frozen=True)

    directory: Path
    report_json: Path
    report_html: Path
    manifest: Path
    quarantine: Path
