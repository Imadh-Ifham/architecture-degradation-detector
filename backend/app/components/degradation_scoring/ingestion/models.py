# Data structures returned by the ingestion subcomponent.

from collections import Counter

from pydantic import BaseModel, ConfigDict, Field

from app.components.degradation_scoring.models import ResolvedEvent
from app.domain.degradation_event import DegradationEventV2
from app.domain.severity_report import QuarantinedEvent, SkippedEvent


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


class IngestionResult(EventIngestion):
    # what ingestion hands on: resolved events to rank, plus what was left out and why
    # (eligible = every event that reached resolution, resolved or not)

    resolved: list[ResolvedEvent] = Field(default_factory=list)
    resolution_rate: float = Field(ge=0, le=1)
