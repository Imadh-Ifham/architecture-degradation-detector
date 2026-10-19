"""Invariance properties of Mann-Kendall and Sen's slope (Hypothesis).

MK depends only on the order of the values, so anything that keeps the order keeps S, tau and p.
Sen's slope is in the units of the values, so it shifts and scales with them.

Values are small integers stored as floats, and the transforms are exact on them, so floating
point rounding can never create or remove a tie and turn a property into a flaky one.
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.components.degradation_detection.trends.mann_kendall import mann_kendall
from app.components.degradation_detection.trends.models import MannKendallResult
from app.components.degradation_detection.trends.sens_slope import sens_slope
from app.domain.degradation_event import TestMethod

# A smaller permutation count keeps the property runs fast; the properties hold for any count.
N_PERM = 2_000
SEED = 20261013

series = st.lists(st.integers(-50, 50), min_size=2, max_size=14).map(
    lambda values: [float(v) for v in values]
)


def _mk(values: list[float]) -> MannKendallResult:
    return mann_kendall(values, exact_below=10, n_perm=N_PERM, seed=SEED)


def _times(n: int) -> list[float]:
    # A gap in the middle, so the properties also cover a non-contiguous time axis.
    return [float(t if t < n // 2 else t + 2) for t in range(n)]


def _same_test(a: MannKendallResult, b: MannKendallResult) -> None:
    assert (a.s, a.method) == (b.s, b.method)
    assert a.tau == pytest.approx(b.tau)
    assert a.p_value == pytest.approx(b.p_value)
    assert (a.tau_b is None) == (b.tau_b is None)


@settings(deadline=None)
@given(series)
def test_p_and_tau_are_in_range(values: list[float]) -> None:
    result = _mk(values)

    assert 0 < result.p_value <= 1
    assert -1 <= result.tau <= 1
    assert abs(result.s) <= result.n * (result.n - 1) // 2


@settings(deadline=None)
@given(series)
def test_reversing_the_series_negates_s(values: list[float]) -> None:
    forward, backward = _mk(values), _mk(values[::-1])

    assert backward.s == -forward.s
    assert backward.tau == pytest.approx(-forward.tau)
    assert backward.method is forward.method
    if forward.method is not TestMethod.PERMUTATION:  # a new shuffle sample, same distribution
        assert backward.p_value == pytest.approx(forward.p_value)


@settings(deadline=None)
@given(series, st.integers(-1000, 1000))
def test_adding_a_constant_changes_nothing_but_the_intercept(values: list[float], c: int) -> None:
    shifted = [v + c for v in values]
    times = _times(len(values))

    _same_test(_mk(values), _mk(shifted))
    before, after = sens_slope(times, values), sens_slope(times, shifted)
    assert after.slope == pytest.approx(before.slope)
    assert after.intercept == pytest.approx(before.intercept + c)


@settings(deadline=None)
@given(series, st.sampled_from([0.25, 0.5, 2.0, 3.0, 7.0]))
def test_positive_scaling_keeps_the_test_and_scales_the_slope(
    values: list[float], a: float
) -> None:
    scaled = [v * a for v in values]
    times = _times(len(values))

    _same_test(_mk(values), _mk(scaled))
    assert sens_slope(times, scaled).slope == pytest.approx(a * sens_slope(times, values).slope)


@settings(deadline=None)
@given(series)
def test_strictly_monotone_transform_keeps_tau(values: list[float]) -> None:
    # x^3 + 2x is strictly increasing, and exact on these integers.
    transformed = [v**3 + 2 * v for v in values]

    _same_test(_mk(values), _mk(transformed))
    assert _mk(transformed).tau_b == _mk(values).tau_b
