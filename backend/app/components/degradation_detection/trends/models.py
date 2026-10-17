"""M4 models used only inside trends: the raw results of the statistical core, what was not
tested and why, and the analysis of one run.

The analyzer combines the core's results with the series identity, the BH q-value and the
metric's worsening direction into ``TrendResult`` (component ``models.py``), which the event
export reads.
"""

from pydantic import Field

from app.components.degradation_detection.models import (
    EventCandidate,
    InternalModel,
    TrendResult,
)
from app.domain.degradation_event import Scope, TestMethod

# Reason codes M4 logs.
SERIES_TOO_SHORT = "SERIES_TOO_SHORT"  # fewer than min_releases non-null points [D-03]
NO_WORSENING_DIRECTION = "NO_WORSENING_DIRECTION"  # supports detectors only (instability)
TREND_ON_ENDED_INSTANCE = "TREND_ON_ENDED_INSTANCE"  # instance not in the last release
CANDIDATE_INSTANCE_AMBIGUOUS = "CANDIDATE_INSTANCE_AMBIGUOUS"  # two instances of one type


class MannKendallResult(InternalModel):
    n: int = Field(ge=2)
    s: int
    # Tie-corrected variance of S and the continuity-corrected z: set only by the NORMAL method,
    # the one that uses them.
    var_s: float | None = None
    z: float | None = None
    tau: float = Field(ge=-1, le=1)  # tau-a: S / (n(n-1)/2)
    tau_b: float | None = Field(default=None, ge=-1, le=1)  # null for a constant series
    p_value: float = Field(ge=0, le=1)  # two-sided [D-01]
    method: TestMethod


class SenSlope(InternalModel):
    slope: float  # change per unit of the time axis given (per release on the ordinal axis)
    intercept: float  # median(x) - slope * median(t)


class UntestedSeries(InternalModel):
    """A series M4 did not test, and why; the run reports how many [D-03]."""

    scope: Scope
    subject_id: str
    metric: str
    reason: str
    n_points: int = Field(ge=0)  # non-null points


class TrendAnalysis(InternalModel):
    """Everything M4 found in one system run."""

    results: tuple[TrendResult, ...]  # every tested series, significant or not
    untested: tuple[UntestedSeries, ...]
    candidates: tuple[EventCandidate, ...]
