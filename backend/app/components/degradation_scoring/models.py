# Data structures shared by two or more C4 subcomponents.
# Contracts shared with other components live in app/domain/ instead.

from pydantic import BaseModel, ConfigDict, Field

from app.domain.degradation_event import DegradationEventV2
from app.domain.severity_report import Resolution


class ResolvedEvent(BaseModel):
    # an eligible event with the graph nodes its elements map to

    model_config = ConfigDict(frozen=True)

    event: DegradationEventV2
    nodes: list[str] = Field(min_length=1)
    resolution: Resolution
