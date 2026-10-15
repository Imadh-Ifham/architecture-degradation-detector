"""Internal C3 models and enums shared by two or more subcomponents.

Pure data, no I/O. Internal models use ``extra="forbid"`` and are immutable. Models that cross a
port (``CanonicalRelease``...) and the enums that appear in the contracts (``Scope``,
``Worsening``, ``TestMethod``, ``ArchitectureStyle``...) live in ``app/domain/``.

Lineage, instance-track and graph models are added by the tasks that build them (T-05, T-08,
T-09).
"""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.canonical_release import CanonicalRelease, IntentEntry
from app.domain.degradation_event import Scope, TestMethod, Worsening


class MetricLevel(StrEnum):
    ELEMENT = "element"
    SYSTEM = "system"


class TrendKind(StrEnum):
    GRADUAL_DRIFT = "GRADUAL_DRIFT"
    STEP_CHANGE = "STEP_CHANGE"


class InternalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- M1 output: the timeline of one system, computed at the start of every run -------------


class TimelineEntry(InternalModel):
    # Position on this run's timeline. Computed per run, never stored as identity.
    ordinal: int = Field(ge=0)
    release: CanonicalRelease


class IntentRecord(InternalModel):
    """One intent, deduplicated across the releases of the timeline (plan M1, step 8)."""

    intent: IntentEntry  # as stated by the latest release that carries it
    first_seen_release: str
    last_seen_release: str


class Timeline(InternalModel):
    system_id: str
    entries: tuple[TimelineEntry, ...]
    intents: tuple[IntentRecord, ...] = ()


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
