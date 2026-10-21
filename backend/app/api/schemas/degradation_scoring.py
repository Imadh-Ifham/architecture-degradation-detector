# HTTP response models of the degradation scoring (C4) read API. The report itself is the
# domain contract SeverityReportV1 (app/domain/severity_report.py), returned unchanged.

import datetime as dt

from pydantic import BaseModel, Field

from app.domain.severity_report import DataProvenance, Dimension


class ScoringRunRequest(BaseModel):
    repository_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
        max_length=128,
        description="The repository detection ran on, e.g. microservices-demo-65bf2e173bd5.",
    )
    detection_run_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
        max_length=128,
        description="The detection run to score; its hand-over files are read unchanged.",
    )


class ScoringRunCountsResponse(BaseModel):
    payloads: int = Field(description="Event payloads the run received from C3.")
    ranked: int = Field(description="Events ranked in the report.")
    skipped: int = Field(
        description="Valid events not ranked: rejected, intentional, system scope or superseded."
    )
    quarantined: int = Field(description="Malformed payloads or events whose elements are unknown.")


class ScoringRunResponse(BaseModel):
    run_id: str = Field(description="Run id; use it to fetch the report.")
    system_id: str = Field(description="The analysed system, e.g. online-boutique.")
    release_id: str = Field(description="The release the events were detected at.")
    data_provenance: DataProvenance = Field(
        description="fixture, fixture-events+live-history or live. Anything but live means "
        "hand-made inputs: show a fixture banner."
    )
    active_dimensions: list[Dimension] = Field(
        description="Criteria used for ranking; the others are off (weight 0)."
    )
    counts: ScoringRunCountsResponse
    resolution_rate: float = Field(
        description="Share of eligible events whose elements were found in the graph (0-1)."
    )
    created_at: dt.datetime = Field(description="When the run was written (UTC).")
