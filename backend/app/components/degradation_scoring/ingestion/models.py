# Data structures returned by the ingestion subcomponent.

from collections import Counter

from pydantic import BaseModel, ConfigDict, Field

from app.domain.degradation_event import DegradationEventV2
from app.domain.severity_report import QuarantinedEvent, Resolution, SkippedEvent


class EventIngestion(BaseModel):
    # payloads sorted into eligible, quarantined and skipped

    model_config = ConfigDict(frozen=True)

    eligible: list[DegradationEventV2] = Field(default_factory=list)
    quarantined: list[QuarantinedEvent] = Field(default_factory=list)
    skipped: list[SkippedEvent] = Field(default_factory=list)

    def quarantine_counts(self) -> dict[str, int]:
        return dict(Counter(str(item.reason) for item in self.quarantined))

    def skip_counts(self) -> dict[str, int]:
        return dict(Counter(str(item.reason) for item in self.skipped))


class ResolvedEvent(BaseModel):
    # an eligible event with the graph nodes its elements map to

    model_config = ConfigDict(frozen=True)

    event: DegradationEventV2
    nodes: list[str] = Field(min_length=1)
    resolution: Resolution


class IngestionResult(EventIngestion):
    # what ingestion hands on: resolved events to rank, plus what was left out and why
    # (eligible = every event that reached resolution, resolved or not)

    resolved: list[ResolvedEvent] = Field(default_factory=list)
    resolution_rate: float = Field(ge=0, le=1)
