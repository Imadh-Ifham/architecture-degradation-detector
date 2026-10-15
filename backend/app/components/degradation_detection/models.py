"""Internal C3 models and enums shared by two or more subcomponents.

Pure data, no I/O. Internal models use ``extra="forbid"`` and are immutable; the
tolerant-reader boundary contracts live in ``app/domain/``, and the enums that appear in those
contracts (``Scope``, ``Worsening``, ``TestMethod``, ``ArchitectureStyle``...) are defined there.

Lineage, instance-track and graph models are added by the tasks that build them (T-05, T-08,
T-09).
"""

import datetime as dt
from enum import StrEnum
from typing import Any, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.domain.degradation_event import Scope, TestMethod, Worsening
from app.domain.release_package import ArchitectureStyle


class GateStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    DOWNWEIGHTED = "DOWNWEIGHTED"
    EXCLUDED = "EXCLUDED"


class MetricLevel(StrEnum):
    ELEMENT = "element"
    SYSTEM = "system"


class TrendKind(StrEnum):
    GRADUAL_DRIFT = "GRADUAL_DRIFT"
    STEP_CHANGE = "STEP_CHANGE"


class InternalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- M1 output: one normalised release ---------------------------------------------------


class ElementSnapshot(InternalModel):
    element_id: str
    name: str
    kind: str
    size: float | None = None
    size_unit: str | None = None
    aliases: tuple[str, ...] = ()
    layer: str | None = None
    metrics: dict[str, float | None] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)


class DependencyEdge(InternalModel):
    from_id: str
    to_id: str
    types: tuple[str, ...] = ()
    count: int = Field(ge=1)


class IntentEntry(InternalModel):
    intent_id: str
    element_id: str | None = None
    source_type: str
    ref: str | None = None
    decision: str
    decision_kind: str | None = None
    date: dt.date | None = None


class DatastoreAccess(InternalModel):
    element_id: str
    datastore: str
    mode: str | None = None


class CanonicalRelease(InternalModel):
    system_id: str
    release_id: str
    released_at: AwareDatetime
    architecture_style: ArchitectureStyle
    granularity: str
    validation_confidence: float
    gate_status: GateStatus
    package_hash: str
    elements: tuple[ElementSnapshot, ...]
    dependencies: tuple[DependencyEdge, ...] = ()
    intent: tuple[IntentEntry, ...] = ()
    # None means "not supplied by C2", which is different from an empty tuple.
    datastore_access: tuple[DatastoreAccess, ...] | None = None
    delegation: tuple[dict[str, Any], ...] | None = None
    c1_model_ref: str | None = None
    c2_validation_ref: str | None = None


# --- M2 output: metrics and anti-pattern instances per release ----------------------------


class MetricDef(InternalModel):
    name: str
    level: MetricLevel
    unit: str
    # None: the metric supports detectors but has no worsening direction (e.g. instability).
    worsening: Worsening | None = None


class MetricObservation(InternalModel):
    release_id: str
    element_id: str | None  # None for a system-level metric
    metric: str
    value: float | None  # null stays null, never 0


class AntiPatternInstance(InternalModel):
    release_id: str
    local_instance_id: str
    anti_pattern_type: str
    catalog: str
    scope: Scope
    members: tuple[str, ...]
    measures: dict[str, float | None] = Field(default_factory=dict)


# --- M3 output: series across releases ----------------------------------------------------


class SeriesPoint(InternalModel):
    ordinal: int = Field(ge=0)
    release_id: str
    value: float | None  # null stays null, never 0


class Series(InternalModel):
    scope: Scope
    subject_id: str
    metric: str
    points: tuple[SeriesPoint, ...]

    @model_validator(mode="after")
    def _check_ordinals_increase(self) -> Self:
        ordinals = [point.ordinal for point in self.points]
        if any(later <= earlier for earlier, later in zip(ordinals, ordinals[1:], strict=False)):
            raise ValueError("series ordinals must be strictly increasing")
        return self


# --- M4 output: trend results and event candidates ----------------------------------------


class TrendResult(InternalModel):
    scope: Scope
    subject_id: str
    metric: str
    n: int
    s: int
    var_s: float | None = None
    z: float | None = None
    tau: float
    p_value: float
    q_value: float | None = None  # set by Benjamini-Hochberg across the run
    method: TestMethod
    sen_slope: float | None = None
    intercept: float | None = None
    is_worsening: bool = False
    is_significant: bool = False


class EventCandidate(InternalModel):
    event_key: str
    scope: Scope
    subject_id: str
    anti_pattern_type: str
    catalog: str
    start_release: str
    end_release: str
    n_releases: int
    low_confidence_releases: tuple[str, ...] = ()
    trends: tuple[TrendResult, ...]
    trend_strength: float
