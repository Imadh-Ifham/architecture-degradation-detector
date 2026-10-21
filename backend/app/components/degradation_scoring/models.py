# Data structures shared by two or more C4 subcomponents.
# Contracts shared with other components live in app/domain/ instead.

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.domain.degradation_event import DegradationEventV2
from app.domain.severity_report import DataProvenance, Dimension, Resolution


class ResolvedEvent(BaseModel):
    # an eligible event with the graph nodes its elements map to

    model_config = ConfigDict(frozen=True)

    event: DegradationEventV2
    nodes: list[str] = Field(min_length=1)
    resolution: Resolution


class AdrRecord(BaseModel):
    # one architecture decision record: normalised status and scope (CLAUDE.md §5.3)

    model_config = ConfigDict(frozen=True)

    adr_id: str
    title: str
    status: str
    scope: str


class AdrIndex(BaseModel):
    # the ADRs of one system plus C2's element -> violated ADR links (adr_refs)

    model_config = ConfigDict(frozen=True)

    adrs: dict[str, AdrRecord] = Field(default_factory=dict)
    links: dict[str, list[str]] = Field(default_factory=dict)


class SavedRunCounts(BaseModel):
    # how many input payloads a saved run had and what happened to them

    model_config = ConfigDict(frozen=True)

    payloads: int = Field(ge=0)
    ranked: int = Field(ge=0)
    skipped: int = Field(ge=0)
    quarantined: int = Field(ge=0)


class SavedRun(BaseModel):
    # one saved rank run, read back from its manifest for the read API

    model_config = ConfigDict(frozen=True)

    run_id: str
    system_id: str
    release_id: str
    data_provenance: DataProvenance
    active_dimensions: list[Dimension]
    counts: SavedRunCounts
    resolution_rate: float = Field(ge=0, le=1)
    created_at: dt.datetime
