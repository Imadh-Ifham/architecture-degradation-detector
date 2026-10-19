"""Benjamini-Hochberg q-values over one family of p-values (all series of one run, [D-26]).

``statsmodels.stats.multitest.multipletests(method="fdr_bh")`` is a dev-only oracle.
"""

import math

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from statsmodels.stats.multitest import multipletests

from app.components.degradation_detection.trends.multiple_testing import benjamini_hochberg


def test_hand_example() -> None:
    # Sorted: 0.005 (rank 1), 0.01 (2), 0.03 (3), 0.04 (4); m = 4.
    # p * m / rank: 0.02, 0.02, 0.04, 0.04; already non-decreasing, returned in input order.
    q = benjamini_hochberg([0.01, 0.04, 0.03, 0.005])

    assert q == pytest.approx((0.02, 0.04, 0.04, 0.02))


def test_step_up_takes_the_minimum_over_larger_ranks() -> None:
    # p * m / rank: 0.03, 0.03, 0.025. The last one pulls the first two down.
    assert benjamini_hochberg([0.01, 0.02, 0.025]) == pytest.approx((0.025, 0.025, 0.025))


def test_q_is_capped_at_one() -> None:
    assert benjamini_hochberg([0.9, 0.95]) == pytest.approx((0.95, 0.95))
    assert benjamini_hochberg([1.0, 1.0, 1.0]) == (1.0, 1.0, 1.0)


def test_equal_p_values_get_equal_q_values() -> None:
    q = benjamini_hochberg([0.02, 0.5, 0.02, 0.02])

    assert q[0] == q[2] == q[3]


def test_rounding_never_puts_q_below_p() -> None:
    # Found by Hypothesis: (p * 3) / 3 rounds one ulp below p; p * (3 / 3) does not.
    p = 0.8283717986556753

    assert benjamini_hochberg([0.0, 0.0, p])[2] >= p


def test_single_and_empty_family() -> None:
    assert benjamini_hochberg([0.03]) == (0.03,)
    assert benjamini_hochberg([]) == ()


@pytest.mark.parametrize("seed", range(30))
def test_matches_statsmodels(seed: int) -> None:
    rng = np.random.default_rng(seed)
    m = int(rng.integers(1, 200))
    p = rng.uniform(0, 1, m) ** 3  # skewed towards 0, like a family with some real trends
    p[rng.integers(0, m, m // 5)] = p[0]  # some ties

    expected = multipletests(p, method="fdr_bh")[1]

    assert benjamini_hochberg([float(v) for v in p]) == pytest.approx(tuple(expected))


@given(st.lists(st.floats(min_value=0, max_value=1), max_size=60))
def test_q_is_at_least_p_at_most_one_and_monotone_in_p(p: list[float]) -> None:
    q = benjamini_hochberg(p)

    assert len(q) == len(p)
    for p_i, q_i in zip(p, q, strict=True):
        assert p_i <= q_i <= 1
    for (p_i, q_i), (p_j, q_j) in zip(
        sorted(zip(p, q, strict=True)), sorted(zip(p, q, strict=True))[1:], strict=False
    ):
        assert p_i <= p_j and q_i <= q_j


@pytest.mark.parametrize("bad", [-0.1, 1.1, math.nan, math.inf])
def test_invalid_p_raises(bad: float) -> None:
    with pytest.raises(ValueError):
        benjamini_hochberg([0.1, bad])
