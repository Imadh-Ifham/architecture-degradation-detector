"""Sen's slope: median of pairwise slopes over an explicit time axis.

The time axis is passed in, never derived from list positions. A release with a null value is
simply absent from both lists, so the gap stays in time. Re-indexing would squash it and inflate
the slope. ``scipy.stats.theilslopes`` is a dev-only oracle.
"""

import math

import numpy as np
import pytest
from scipy import stats

from app.components.degradation_detection.trends.sens_slope import sens_slope


def _line(times: list[int]) -> list[float]:
    return [3 + 0.8 * t for t in times]


def test_recovers_planted_slope_and_intercept() -> None:
    times = list(range(10))

    result = sens_slope(times, _line(times))

    assert result.slope == pytest.approx(0.8)
    assert result.intercept == pytest.approx(3.0)


def test_gap_in_time_is_kept() -> None:
    # Releases 3 and 6 had null values: they are absent, not re-indexed.
    times = [0, 1, 2, 4, 5, 7, 8, 9]
    values = _line(times)

    assert sens_slope(times, values).slope == pytest.approx(0.8)
    # What a library that re-indexes would report: a steeper, wrong slope.
    assert sens_slope(list(range(len(values))), values).slope > 0.9


def test_survives_one_outlier() -> None:
    times = list(range(10))
    values = _line(times)
    values[4] = 100.0

    # 36 of the 45 pairwise slopes do not touch the outlier and are exactly 0.8.
    assert sens_slope(times, values).slope == pytest.approx(0.8)


def test_constant_series_has_zero_slope() -> None:
    result = sens_slope([0, 1, 2, 3], [5.0] * 4)

    assert result.slope == 0.0
    assert result.intercept == 5.0


def test_two_points() -> None:
    result = sens_slope([2, 5], [1.0, 7.0])

    assert result.slope == pytest.approx(2.0)
    assert result.intercept == pytest.approx(4.0 - 2.0 * 3.5)


@pytest.mark.parametrize("seed", range(30))
def test_matches_scipy_theilslopes(seed: int) -> None:
    rng = np.random.default_rng(seed)
    n = int(rng.integers(3, 25))
    times = sorted(int(t) for t in rng.choice(40, size=n, replace=False))
    values = [float(0.5 * t + rng.normal(0, 2)) for t in times]

    result = sens_slope(times, values)
    oracle = stats.theilslopes(values, times)

    assert result.slope == pytest.approx(oracle.slope)
    assert result.intercept == pytest.approx(oracle.intercept)


@pytest.mark.parametrize("times", [[0, 1, 1, 2], [0, 2, 1, 3], [3, 2, 1, 0]])
def test_non_increasing_time_raises(times: list[int]) -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        sens_slope(times, [1.0, 2.0, 3.0, 4.0])


@pytest.mark.parametrize(
    ("times", "values"),
    [
        ([0, 1, 2], [1.0, 2.0]),  # length mismatch
        ([0], [1.0]),  # one point: no pair
        ([], []),
        ([0, 1, 2], [1.0, math.nan, 2.0]),
        ([0, math.inf], [1.0, 2.0]),
    ],
)
def test_invalid_input_raises(times: list[float], values: list[float]) -> None:
    with pytest.raises(ValueError):
        sens_slope(times, values)
