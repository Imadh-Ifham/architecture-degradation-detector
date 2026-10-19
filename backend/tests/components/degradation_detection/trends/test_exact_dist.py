"""The Mahonian distribution: number of permutations of n distinct items with k inversions.

It is the exact null distribution of the Mann-Kendall S for a tie-free series (S = N - 2k,
N = n(n-1)/2), so the exact p-value is only as right as this table.
"""

import itertools
import math

import pytest

from app.components.degradation_detection.trends.exact_dist import exact_two_sided_p, mahonian


def _inversions(order: tuple[int, ...]) -> int:
    return sum(a > b for a, b in itertools.combinations(order, 2))


@pytest.mark.parametrize("n", range(11))
def test_counts_sum_to_n_factorial(n: int) -> None:
    assert sum(mahonian(n)) == math.factorial(n)


@pytest.mark.parametrize("n", range(11))
def test_counts_are_symmetric(n: int) -> None:
    # Reversing a permutation turns k inversions into N - k.
    counts = mahonian(n)

    assert counts == counts[::-1]
    assert len(counts) == n * (n - 1) // 2 + 1


def test_small_tables() -> None:
    assert mahonian(0) == (1,)
    assert mahonian(1) == (1,)
    assert mahonian(3) == (1, 2, 2, 1)
    assert mahonian(4) == (1, 3, 5, 6, 5, 3, 1)


@pytest.mark.parametrize("n", range(1, 7))
def test_counts_match_brute_force_enumeration(n: int) -> None:
    counts = [0] * (n * (n - 1) // 2 + 1)
    for order in itertools.permutations(range(n)):
        counts[_inversions(order)] += 1

    assert mahonian(n) == tuple(counts)


def test_negative_n_raises() -> None:
    with pytest.raises(ValueError):
        mahonian(-1)


def test_exact_p_sanity_values() -> None:
    # Strictly monotone: only the identity (or its reverse) reaches |S| = N.
    assert exact_two_sided_p(5, 10) == pytest.approx(2 / 120)
    assert exact_two_sided_p(5, -10) == pytest.approx(2 / 120)
    assert exact_two_sided_p(4, 6) == pytest.approx(2 / 24)


def test_exact_p_of_zero_is_one() -> None:
    assert exact_two_sided_p(4, 0) == 1.0


def test_n4_can_never_reach_five_percent() -> None:
    assert min(exact_two_sided_p(4, s) for s in range(-6, 7, 2)) > 0.05


@pytest.mark.parametrize(("n", "s"), [(4, 7), (4, 1), (5, 12), (5, -11), (1, 1)])
def test_impossible_s_raises(n: int, s: int) -> None:
    # S has the parity of N and |S| <= N.
    with pytest.raises(ValueError):
        exact_two_sided_p(n, s)
