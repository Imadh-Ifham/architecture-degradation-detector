"""M4 models used only inside trends: the raw results of the statistical core.

The analyzer (T-12) combines them with the series identity, the BH q-value and the metric's
worsening direction into ``TrendResult`` (component ``models.py``), which the event export reads.
"""

from pydantic import Field

from app.components.degradation_detection.models import InternalModel
from app.domain.degradation_event import TestMethod


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
