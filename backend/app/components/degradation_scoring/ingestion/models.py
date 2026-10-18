# Data structures returned by the ingestion subcomponent.

from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.components.degradation_scoring.models import AdrIndex, ResolvedEvent
from app.domain.degradation_event import DegradationEventV2
from app.domain.severity_report import QuarantinedEvent, SkippedEvent


class PayloadRecord(BaseModel):
    # what happened to one input payload, by its position (malformed payloads may lack an id)

    model_config = ConfigDict(frozen=True)

    payload_index: int = Field(ge=0)
    event_id: str | None = None
    scope: str | None = None
    anti_pattern_type: str | None = None
    review_status: str | None = None
    context_tag: str | None = None
    outcome: Literal["eligible", "ranked", "skipped", "quarantined"]
    reason: str | None = None
    detail: str | None = None
    nodes: list[str] = Field(default_factory=list)
    resolution_status: str | None = None
    resolution_confidence: float | None = None


class EventIngestion(BaseModel):
    # payloads sorted into eligible, quarantined and skipped; payloads = one record each

    model_config = ConfigDict(frozen=True)

    eligible: list[DegradationEventV2] = Field(default_factory=list)
    quarantined: list[QuarantinedEvent] = Field(default_factory=list)
    skipped: list[SkippedEvent] = Field(default_factory=list)
    payloads: list[PayloadRecord] = Field(default_factory=list)

    def quarantine_counts(self) -> dict[str, int]:
        return dict(Counter(str(item.reason) for item in self.quarantined))

    def skip_counts(self) -> dict[str, int]:
        return dict(Counter(str(item.reason) for item in self.skipped))


class IngestionResult(EventIngestion):
    # what ingestion hands on: resolved events to rank, plus what was left out and why
    # (eligible = every event that reached resolution, resolved or not)

    resolved: list[ResolvedEvent] = Field(default_factory=list)
    resolution_rate: float = Field(ge=0, le=1)
    adr_index: AdrIndex | None = None
