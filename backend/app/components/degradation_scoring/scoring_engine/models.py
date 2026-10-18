# Data structures of the scoring_engine subcomponent.

from pydantic import BaseModel, ConfigDict, Field

from app.domain.severity_report import Dimension, NormalizationMode


class RawEvent(BaseModel):
    # one event's raw feature values, keyed like c4_event_features (br_*, eh_*, ps_*, av_weight);
    # built by <C4>/service.py, because subcomponents never import each other

    model_config = ConfigDict(frozen=True)

    event_id: str
    values: dict[str, float]


class FeatureBounds(BaseModel):
    # the [lower, upper] scale of one feature; fallback says why plain min-max was used
    # (sparse_minmax: P5 = P95 although the values differ, C4-ADR-013)

    model_config = ConfigDict(frozen=True)

    lower: float
    upper: float
    fallback: str | None = None


class Calibration(BaseModel):
    # bounds fitted on one run, saved so later runs reuse the same scale (CLAUDE.md §5.5)

    model_config = ConfigDict(frozen=True)

    system_id: str
    release_id: str
    mode: NormalizationMode
    n_events: int = Field(ge=0)
    lower_percentile: float
    upper_percentile: float
    bounds: dict[str, FeatureBounds]


class NormalisedEvent(BaseModel):
    # one event's features on [0, 1] and one value per active criterion

    model_config = ConfigDict(frozen=True)

    event_id: str
    features: dict[str, float]
    criteria: dict[Dimension, float]


class NormalisedSet(BaseModel):
    # what the normaliser hands on: events in input order, the scale used and whether it
    # was loaded (frozen) rather than fitted on these events

    model_config = ConfigDict(frozen=True)

    events: list[NormalisedEvent]
    active_criteria: list[Dimension]
    mode: NormalizationMode
    frozen: bool
    calibration: Calibration
