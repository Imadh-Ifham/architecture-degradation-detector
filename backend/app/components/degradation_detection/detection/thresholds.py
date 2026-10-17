"""Relative thresholds: where a value sits within its own release's distribution (pure).

Detectors never compare a metric with an absolute number. They compare it with the release it
came from, so a system that grows as a whole does not make every element look anomalous:

- **Upper IQR fence** (Tukey): ``Q3 + k * IQR``. Quartiles are the inclusive definition
  (Hyndman-Fan type 7; the default of numpy, R and Excel ``QUARTILE.INC``; owner decision,
  T-06), so anyone can reproduce a fence with a spreadsheet.
- **Robust z**: ``(x - median) / (1.4826 * MAD)``. Median and MAD are not dragged by the
  outlier being looked for, unlike a mean and standard deviation.

The multipliers (``k``, the z limit) come from config. The constants here are properties of the
estimators, not tunable thresholds.
"""

import statistics
from collections.abc import Iterable, Mapping

# Scales the median absolute deviation to the standard deviation of a normal distribution, so a
# robust z reads like an ordinary z.
MAD_TO_SIGMA = 1.4826


def upper_iqr_fence(values: Iterable[float], k: float) -> float | None:
    """``Q3 + k * IQR``, or None with fewer than two values (no spread to speak of)."""
    data = list(values)
    if len(data) < 2:
        return None
    q1, _, q3 = statistics.quantiles(data, n=4, method="inclusive")
    return q3 + k * (q3 - q1)


def robust_z(values: Mapping[str, float]) -> dict[str, float] | None:
    """Robust z of every value, or None when undefined (no values, or MAD = 0).

    MAD = 0 means more than half the values are equal: there is no spread to measure against, so
    the answer is "unknown" (null), not "no outlier" (0).
    """
    if not values:
        return None
    median = statistics.median(values.values())
    mad = statistics.median(abs(value - median) for value in values.values())
    if mad == 0:
        return None
    scale = MAD_TO_SIGMA * mad
    return {key: (value - median) / scale for key, value in values.items()}
