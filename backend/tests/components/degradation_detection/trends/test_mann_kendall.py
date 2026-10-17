"""Mann-Kendall: S, tau, and the two-sided p by the method the series calls for.

Method choice (``exact_below`` = 10 in the default config):

- constant series -> DEGENERATE, p = 1 (no ordering information at all);
- n < 10, no ties -> EXACT, from the Mahonian distribution;
- n < 10, ties -> PERMUTATION (ties change the null distribution, the table would be wrong);
- n >= 10 -> NORMAL, tie-corrected variance and continuity correction.

``scipy.stats.kendalltau`` and ``pymannkendall`` are dev-only oracles; neither is a runtime import.
"""

import itertools
import math

import numpy as np
import pymannkendall
import pytest
from scipy import stats

from app.components.degradation_detection.trends.exact_dist import exact_two_sided_p
from app.components.degradation_detection.trends.mann_kendall import (
    kendall_s,
    mann_kendall,
    permutation_p,
)
from app.components.degradation_detection.trends.models import MannKendallResult
from app.domain.degradation_event import TestMethod

EXACT_BELOW = 10
N_PERM = 20_000
SEED = 20261013


def _mk(values: list[float], exact_below: int = EXACT_BELOW) -> MannKendallResult:
    return mann_kendall(values, exact_below=exact_below, n_perm=N_PERM, seed=SEED)


def _monte_carlo_tolerance(p: float) -> float:
    # Four standard errors of a proportion estimated from N_PERM draws, plus the +1 correction.
    return 4 * math.sqrt(p * (1 - p) / N_PERM) + 2 / N_PERM


# --- known series -------------------------------------------------------------------------


def test_n5_strictly_increasing() -> None:
    result = mann_kendall([1, 2, 3, 4, 5], exact_below=EXACT_BELOW, n_perm=N_PERM, seed=SEED)

    assert result.n == 5
    assert result.s == 10
    assert result.tau == 1.0
    assert result.tau_b == 1.0
    assert result.p_value == pytest.approx(2 / 120)
    assert result.method is TestMethod.EXACT
    assert result.var_s is None
    assert result.z is None


def test_n5_strictly_decreasing_is_the_mirror_image() -> None:
    result = mann_kendall([5, 4, 3, 2, 1], exact_below=EXACT_BELOW, n_perm=N_PERM, seed=SEED)

    assert result.s == -10
    assert result.tau == -1.0
    assert result.p_value == pytest.approx(2 / 120)


def test_n4_strictly_increasing_cannot_reach_five_percent() -> None:
    result = mann_kendall([1, 2, 3, 4], exact_below=EXACT_BELOW, n_perm=N_PERM, seed=SEED)

    assert result.s == 6
    assert result.p_value == pytest.approx(2 / 24)
    assert result.p_value > 0.05


@pytest.mark.parametrize("n", [2, 5, 9, 10, 15])
def test_constant_series_is_degenerate(n: int) -> None:
    result = mann_kendall([3.5] * n, exact_below=EXACT_BELOW, n_perm=N_PERM, seed=SEED)

    assert result.method is TestMethod.DEGENERATE
    assert result.s == 0
    assert result.tau == 0.0
    assert result.tau_b is None  # tau-b's denominator is 0: undefined, not 0
    assert result.p_value == 1.0
    assert result.var_s is None
    assert result.z is None


def test_alternating_series_n10_by_hand() -> None:
    # 0,1,0,1,...: concordant pairs (a 0 before a 1) 5+4+3+2+1 = 15, discordant 4+3+2+1 = 10.
    values = [0, 1] * 5
    result = mann_kendall(values, exact_below=EXACT_BELOW, n_perm=N_PERM, seed=SEED)

    # Var = [10*9*25 - 2 * (5*4*15)] / 18 = (2250 - 600) / 18; continuity-corrected z.
    var_s = (2250 - 600) / 18
    z = (5 - 1) / math.sqrt(var_s)
    assert result.method is TestMethod.NORMAL
    assert result.s == 5
    assert result.tau == pytest.approx(5 / 45)
    assert result.var_s == pytest.approx(var_s)
    assert result.z == pytest.approx(z)
    assert result.p_value == pytest.approx(math.erfc(z / math.sqrt(2)))
    assert result.p_value > 0.5


def test_alternating_short_series_with_ties_is_not_significant() -> None:
    result = mann_kendall([0, 1] * 4, exact_below=EXACT_BELOW, n_perm=N_PERM, seed=SEED)

    assert result.method is TestMethod.PERMUTATION
    assert result.s == 4
    assert result.p_value > 0.5


def test_kendall_s_counts_concordant_minus_discordant() -> None:
    # Pairs: (3,1)- (3,2)- (3,5)+ (1,2)+ (1,5)+ (2,5)+  -> 4 - 2 = 2. Ties count 0.
    assert kendall_s([3, 1, 2, 5]) == 2
    assert kendall_s([1, 1, 2]) == 2
    assert kendall_s([2, 2]) == 0


# --- method selection ---------------------------------------------------------------------


def test_method_switches_to_normal_at_exact_below() -> None:
    assert _mk(list(range(9))).method is TestMethod.EXACT
    assert _mk(list(range(10))).method is TestMethod.NORMAL
    assert _mk(list(range(5)), exact_below=5).method is TestMethod.NORMAL


def test_short_series_with_ties_uses_permutation() -> None:
    result = mann_kendall([1, 2, 2, 3, 4], exact_below=EXACT_BELOW, n_perm=N_PERM, seed=SEED)

    assert result.method is TestMethod.PERMUTATION
    assert result.var_s is None
    assert result.z is None


def test_normal_method_reports_variance_and_z() -> None:
    result = mann_kendall(list(range(12)), exact_below=EXACT_BELOW, n_perm=N_PERM, seed=SEED)

    assert result.var_s == pytest.approx(12 * 11 * 29 / 18)
    assert result.z == pytest.approx((66 - 1) / math.sqrt(12 * 11 * 29 / 18))


def test_negative_s_uses_plus_one_continuity_correction() -> None:
    result = mann_kendall(list(range(12, 0, -1)), exact_below=10, n_perm=N_PERM, seed=SEED)

    assert result.s == -66
    assert result.z == pytest.approx((-66 + 1) / math.sqrt(12 * 11 * 29 / 18))


def test_zero_s_gives_zero_z_and_p_one() -> None:
    # 10 values, ties, S = 0 by symmetry.
    values = [1, 2, 3, 4, 5, 5, 4, 3, 2, 1]
    result = mann_kendall(values, exact_below=EXACT_BELOW, n_perm=N_PERM, seed=SEED)

    assert result.s == 0
    assert result.z == 0.0
    assert result.p_value == 1.0


# --- permutation test ---------------------------------------------------------------------


def test_permutation_is_deterministic_for_a_seed() -> None:
    values = [1, 3, 2, 2, 4, 3, 5, 6]
    s = kendall_s(values)

    assert permutation_p(values, s, n_perm=N_PERM, seed=SEED) == permutation_p(
        values, s, n_perm=N_PERM, seed=SEED
    )


def test_permutation_p_is_hits_plus_one_over_draws_plus_one() -> None:
    # The most extreme ordering: p is small but never 0, and an exact multiple of 1/(n_perm+1).
    values = [1, 2, 2, 3, 4, 5, 6, 7]
    p = permutation_p(values, kendall_s(values), n_perm=999, seed=SEED)

    assert p > 0
    assert (p * 1000) == pytest.approx(round(p * 1000))


def test_permutation_p_on_tie_free_series_agrees_with_exact() -> None:
    values = [2, 1, 4, 3, 6, 5, 8, 9, 7]
    s = kendall_s(values)
    exact = exact_two_sided_p(len(values), s)

    p = permutation_p(values, s, n_perm=N_PERM, seed=SEED)

    assert abs(p - exact) <= _monte_carlo_tolerance(exact)


def test_permutation_p_with_ties_agrees_with_full_enumeration() -> None:
    # Oracle: all 8! orderings of the observed values (the exact conditional null with ties).
    values = [1, 3, 2, 2, 4, 3, 5, 6]
    s = kendall_s(values)
    hits = sum(abs(kendall_s(order)) >= abs(s) for order in itertools.permutations(values))
    exact = hits / math.factorial(len(values))

    result = mann_kendall(values, exact_below=EXACT_BELOW, n_perm=N_PERM, seed=SEED)

    assert result.method is TestMethod.PERMUTATION
    assert abs(result.p_value - exact) <= _monte_carlo_tolerance(exact)


# --- oracles ------------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(40))
def test_tie_free_exact_p_matches_scipy(seed: int) -> None:
    rng = np.random.default_rng(seed)
    n = int(rng.integers(3, EXACT_BELOW))
    values = [float(v) for v in rng.permutation(n)]

    result = mann_kendall(values, exact_below=EXACT_BELOW, n_perm=N_PERM, seed=SEED)
    oracle = stats.kendalltau(np.arange(n), values, method="exact")

    assert result.method is TestMethod.EXACT
    assert result.tau == pytest.approx(oracle.statistic)
    assert result.p_value == pytest.approx(oracle.pvalue, abs=1e-12)


@pytest.mark.parametrize("seed", range(40))
@pytest.mark.parametrize("ties", [True, False], ids=["ties", "tie-free"])
def test_normal_method_matches_pymannkendall(seed: int, ties: bool) -> None:
    rng = np.random.default_rng(seed)
    n = int(rng.integers(EXACT_BELOW, 30))
    trend = float(rng.normal(0, 0.3))
    noise = rng.integers(0, 4, n) if ties else rng.normal(0, 1, n)
    values = [float(v) for v in trend * np.arange(n) + noise]
    if ties:
        values = [float(round(v)) for v in values]

    result = mann_kendall(values, exact_below=EXACT_BELOW, n_perm=N_PERM, seed=SEED)
    oracle = pymannkendall.original_test(values)

    if result.method is TestMethod.DEGENERATE:  # rounding made it constant: nothing to compare
        return
    assert result.method is TestMethod.NORMAL
    assert result.s == oracle.s
    assert result.var_s == pytest.approx(oracle.var_s)
    assert result.z == pytest.approx(oracle.z, abs=1e-12)
    assert result.tau == pytest.approx(oracle.Tau)
    assert result.p_value == pytest.approx(oracle.p, abs=1e-12)


@pytest.mark.parametrize(
    "values",
    [[1, 1, 2, 3, 3, 3, 4], [5, 4, 4, 2, 9, 9, 9, 9, 1, 0, 0, 3], [0, 1] * 6],
)
def test_tau_b_matches_scipy(values: list[float]) -> None:
    result = mann_kendall(values, exact_below=EXACT_BELOW, n_perm=N_PERM, seed=SEED)

    assert result.tau_b == pytest.approx(stats.kendalltau(np.arange(len(values)), values).statistic)


# --- input validation ---------------------------------------------------------------------


@pytest.mark.parametrize("values", [[], [1.0], [1.0, math.nan, 2.0], [1.0, math.inf, 2.0]])
def test_invalid_input_raises(values: list[float]) -> None:
    with pytest.raises(ValueError):
        mann_kendall(values, exact_below=EXACT_BELOW, n_perm=N_PERM, seed=SEED)
