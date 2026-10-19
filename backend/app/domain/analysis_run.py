"""Analysis run: what C3 stores for one run of the pipeline (plan Section 2.4, T-13).

These records cross the ``AnalysisRunRepository`` port, so they live in the domain layer:
infrastructure may not import components (INSTRUCTIONS §7.1). They are the stored shape of a
run, separate from the component's internal models; the component service copies its results
into them field by field, and a test keeps the two field-compatible.

What is stored per run:

* the run itself: status, config and its hash, code and library versions, the releases on the
  timeline, stage timings and how many times each reason code was logged;
* the outputs read back by the report and the evaluation: anti-pattern instances per release,
  every series M4 tested or skipped, the events, and the static-threshold baseline's flags.

The intermediate artifacts (observations, lineages, tracks, series) are stored as JSON beside the
run and are not modelled here.

Like ``CanonicalRelease`` these models are strict (``extra="forbid"``) and immutable: C3 builds
them itself, so an unknown field is our own mistake.
"""

from enum import StrEnum
from typing import Any, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.domain.boundary import Sha256
from app.domain.canonical_release import GateStatus
from app.domain.degradation_event import (
    DegradationEventV2,
    Scope,
    TestMethod,
    TimeAxis,
    Worsening,
)


class RunStatus(StrEnum):
    RUNNING = "RUNNING"  # started; outputs not stored yet
    COMPLETED = "COMPLETED"  # every output stored, in one transaction
    FAILED = "FAILED"  # a stage raised; ``error`` says what, no outputs stored


class RunModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunRelease(RunModel):
    """One release on the run's timeline, in timeline order."""

    ordinal: int = Field(ge=0)  # position on this run's timeline, never an identity
    release_id: str
    released_at: AwareDatetime
    gate_status: GateStatus


class AnalysisRun(RunModel):
    run_id: str
    system_id: str
    status: RunStatus
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    config: dict[str, Any]  # the validated config the run used
    config_hash: Sha256
    code_version: str  # git commit of the code that ran, "-dirty" if it had local changes
    lib_versions: dict[str, str]  # libraries whose version can change a number, and python
    releases: tuple[RunRelease, ...]
    timings: dict[str, float] = Field(default_factory=dict)  # seconds per finished stage
    # How often each reason code was logged. None: not counted (yet, or because the logging was
    # not routed through the standard library, where the counter listens). Never {} for that.
    reason_counts: dict[str, int] | None = None
    error: str | None = None

    @model_validator(mode="after")
    def _check_status(self) -> Self:
        if (self.status is RunStatus.RUNNING) != (self.finished_at is None):
            raise ValueError("finished_at is set exactly when the run is no longer RUNNING")
        if (self.status is RunStatus.FAILED) != (self.error is not None):
            raise ValueError("error is set exactly when the run FAILED")
        return self


class InstanceRecord(RunModel):
    """One anti-pattern instance M2 found in one release."""

    release_id: str
    local_instance_id: str
    anti_pattern_type: str
    catalog: str
    scope: Scope
    members: tuple[str, ...]
    measures: dict[str, float | None] = Field(default_factory=dict)


class SeriesPointRecord(RunModel):
    ordinal: int = Field(ge=0)
    release_id: str
    value: float | None  # null stays null, never 0


class TrendRecord(RunModel):
    """One series M4 tested: Mann-Kendall, Sen's slope and the BH q-value (plan M4)."""

    scope: Scope
    subject_id: str
    metric: str
    unit: str
    worsening: Worsening
    points: tuple[SeriesPointRecord, ...]  # the whole series, nulls kept
    n: int = Field(ge=2)
    s: int
    var_s: float | None = None  # NORMAL method only
    z: float | None = None  # NORMAL method only
    tau: float = Field(ge=-1, le=1)
    p_value: float = Field(ge=0, le=1)
    q_value: float = Field(ge=0, le=1)
    method: TestMethod
    time_axis: TimeAxis
    sen_slope: float
    intercept: float
    is_worsening: bool
    is_significant: bool


class UntestedRecord(RunModel):
    """One series M4 did not test, and why [D-03]."""

    scope: Scope
    subject_id: str
    metric: str
    reason: str
    n_points: int = Field(ge=0)  # non-null points


class StaticFlag(RunModel):
    """An element a fixed-threshold tool would flag: ``value`` is above ``threshold``.

    For comparison only (plan T-13, T-14). C3 never decides degradation this way [locked 2].
    """

    release_id: str
    element_id: str
    metric: str
    value: float
    threshold: float


class RunOutputs(RunModel):
    instances: tuple[InstanceRecord, ...] = ()
    trends: tuple[TrendRecord, ...] = ()
    untested: tuple[UntestedRecord, ...] = ()
    events: tuple[DegradationEventV2, ...] = ()
    static_flags: tuple[StaticFlag, ...] = ()


class StoredRun(RunModel):
    """A run and its outputs, as the repository returns it. A run that did not complete has
    empty outputs."""

    run: AnalysisRun
    outputs: RunOutputs
