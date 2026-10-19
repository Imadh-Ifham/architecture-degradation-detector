# Data structures of the scoring_engine subcomponent.

import datetime as dt
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.severity_report import Dimension, NormalizationMode, WeightsProvenance


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


class PairwiseJudgements(BaseModel):
    # one versioned AHP weights file (scoring_engine/weights/<version>.json, CLAUDE.md §5.6);
    # matrix cells are Saaty values written as strings ("3", "1/3"), row i compared to column j

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(pattern=r"^[a-z0-9_]+$")
    criteria: list[Dimension]
    scale: Literal["saaty_1_9"]
    matrix: list[list[str]]
    elicited_by: str = Field(pattern=r"^\S(.*\S)?$")
    date: dt.date
    provenance: WeightsProvenance

    @model_validator(mode="after")
    def _check_criteria(self) -> Self:
        if sorted(self.criteria) != sorted(Dimension):
            raise ValueError(f"criteria must be each of {[d.value for d in Dimension]} once")
        if len(self.matrix) != len(self.criteria):
            raise ValueError("matrix must have one row per criterion")
        return self


class AhpResult(BaseModel):
    # principal-eigenvector weights (matrix order), lambda_max, CI and CR of one matrix

    model_config = ConfigDict(frozen=True)

    weights: list[float]
    lambda_max: float
    consistency_index: float = Field(ge=0)
    consistency_ratio: float = Field(ge=0)


class CriterionWeights(BaseModel):
    # what scoring uses: elicited = AHP weights of all four criteria; weights = the same
    # renormalised over the active criteria (inactive = 0, active sum to 1)

    model_config = ConfigDict(frozen=True)

    version: str
    provenance: WeightsProvenance
    elicited_by: str
    lambda_max: float
    consistency_index: float
    consistency_ratio: float
    active_criteria: list[Dimension]
    elicited: dict[Dimension, float]
    weights: dict[Dimension, float]


TopsisMode = Literal["fixed_reference", "classic"]


class RankedEvent(BaseModel):
    # one event's TOPSIS result: severity = closeness to the ideal, distances to the ideal and
    # anti-ideal, and each criterion's share of the gap to the anti-ideal (all four listed)

    model_config = ConfigDict(frozen=True)

    event_id: str
    rank: int = Field(ge=1)
    severity: float = Field(ge=0, le=1)
    distance_ideal: float = Field(ge=0)
    distance_anti_ideal: float = Field(ge=0)
    contributions: dict[Dimension, float]


class ScoringResult(BaseModel):
    # layer 3 for one (system, release): the scale used, the weights and the ranking (by rank)

    model_config = ConfigDict(frozen=True)

    topsis_mode: TopsisMode
    normalised: NormalisedSet
    weights: CriterionWeights
    ranking: list[RankedEvent]
