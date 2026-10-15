"""Relative thresholds: Tukey's upper IQR fence and the robust z (median / MAD).

Quartiles are the inclusive (type 7) definition, the one numpy, R and Excel QUARTILE.INC use by
default; ``numpy.percentile`` is used below only as an oracle.
"""

import numpy as np
import pytest

from app.components.degradation_detection.detection.thresholds import (
    MAD_TO_SIGMA,
    robust_z,
    upper_iqr_fence,
)


def test_upper_fence_is_q3_plus_k_iqr() -> None:
    # 1..9: inclusive Q1 = 3, Q3 = 7, IQR = 4.
    assert upper_iqr_fence([1, 2, 3, 4, 5, 6, 7, 8, 9], k=1.5) == pytest.approx(7 + 1.5 * 4)


@pytest.mark.parametrize(
    "values",
    [[0, 0, 0, 1, 1, 1, 6], [0, 1, 1, 2], [3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5], [2.5, 0.5]],
)
def test_upper_fence_matches_numpy_linear_quartiles(values: list[float]) -> None:
    q1, q3 = np.percentile(values, [25, 75])

    assert upper_iqr_fence(values, k=1.5) == pytest.approx(q3 + 1.5 * (q3 - q1))


def test_upper_fence_does_not_depend_on_input_order() -> None:
    assert upper_iqr_fence([6, 0, 1, 0, 1], k=1.5) == upper_iqr_fence([0, 0, 1, 1, 6], k=1.5)


def test_upper_fence_with_zero_iqr_is_q3() -> None:
    # Most values equal: nothing above the typical value is tolerated.
    assert upper_iqr_fence([1, 1, 1, 1, 5], k=1.5) == 1


@pytest.mark.parametrize("values", [[], [4.0]])
def test_upper_fence_is_none_without_two_values(values: list[float]) -> None:
    assert upper_iqr_fence(values, k=1.5) is None


def test_robust_z_uses_median_and_scaled_mad() -> None:
    # Median 3, absolute deviations 2,1,0,1,7 -> MAD 1.
    z = robust_z({"a": 1, "b": 2, "c": 3, "d": 4, "e": 10})

    assert z is not None
    assert z["c"] == 0
    assert z["e"] == pytest.approx(7 / MAD_TO_SIGMA)
    assert z["a"] == pytest.approx(-2 / MAD_TO_SIGMA)


def test_robust_z_is_none_when_mad_is_zero() -> None:
    assert robust_z({"a": 5, "b": 5, "c": 5, "d": 100}) is None


def test_robust_z_is_none_without_values() -> None:
    assert robust_z({}) is None
