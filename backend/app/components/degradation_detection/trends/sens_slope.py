"""Sen's slope (Theil-Sen estimator), self-implemented (locked decision 8; pure).

Slope = median of the pairwise slopes ``(x_j - x_i) / (t_j - t_i)``; intercept =
``median(x) - slope * median(t)`` (Conover's form, the one ``scipy.stats.theilslopes`` uses).
A median ignores up to ~29% bad points, so one odd release does not bend the line.

The time axis is explicit [D-05]: the analyzer passes the ordinals of the non-null points. A
release with a null value is absent from both lists and its gap stays in time. Never re-index
(``range(len(x))``): that squashes the gap and inflates the slope.
"""

import math
import statistics
from collections.abc import Sequence

from app.components.degradation_detection.trends.models import SenSlope


def sens_slope(times: Sequence[float], values: Sequence[float]) -> SenSlope:
    t = [float(time) for time in times]
    x = [float(value) for value in values]
    if len(t) != len(x):
        raise ValueError(f"{len(t)} times for {len(x)} values")
    if len(x) < 2:
        raise ValueError(f"Sen's slope needs at least 2 points, got {len(x)}")
    if not all(math.isfinite(v) for v in (*t, *x)):
        raise ValueError("Sen's slope times and values must be finite (drop nulls first)")
    if any(later <= earlier for earlier, later in zip(t, t[1:], strict=False)):
        raise ValueError("Sen's slope times must be strictly increasing")

    slopes = [(x[j] - x[i]) / (t[j] - t[i]) for i in range(len(x)) for j in range(i + 1, len(x))]
    slope = statistics.median(slopes)
    return SenSlope(slope=slope, intercept=statistics.median(x) - slope * statistics.median(t))
