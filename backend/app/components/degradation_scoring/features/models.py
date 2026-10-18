# Data structures returned by the features subcomponent.

from pydantic import BaseModel, ConfigDict, Field


class BlastRadiusFeatures(BaseModel):
    # the four raw BR features of one event; combined into one score in T17

    model_config = ConfigDict(frozen=True)

    fan_in_ratio: float = Field(ge=0, le=1)
    pagerank: float = Field(ge=0)
    betweenness: float = Field(ge=0)
    depth: int = Field(ge=0)
    betweenness_sampled: bool = False


class EventFeatures(BaseModel):
    # every criterion's features for one resolved event; EH, AV and PS join in T13-T16

    model_config = ConfigDict(frozen=True)

    event_id: str
    blast_radius: BlastRadiusFeatures
