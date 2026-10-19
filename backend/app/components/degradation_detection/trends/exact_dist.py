"""Exact null distribution of the Mann-Kendall S for a tie-free series (pure, stdlib only).

Under H0 (no trend) every ordering of n distinct values is equally likely. S counts concordant
minus discordant pairs, so ``S = N - 2k`` with ``N = n(n-1)/2`` and ``k`` the number of
inversions. The number of permutations with ``k`` inversions is the Mahonian number ``M(n, k)``,
so ``P(S = N - 2k) = M(n, k) / n!``.

Recurrence: placing the n-th (largest) item in one of n positions of an ordering of n-1 items adds
0 .. n-1 inversions, so ``M(n, k) = sum(M(n-1, k-j) for j in 0 .. n-1)``.

Counts are exact integers; the only rounding is the final division.
"""

import math
from functools import cache


@cache
def mahonian(n: int) -> tuple[int, ...]:
    """``M(n, k)`` for ``k = 0 .. n(n-1)/2``."""
    if n < 0:
        raise ValueError(f"n must be >= 0, got {n}")
    counts: tuple[int, ...] = (1,)
    for size in range(2, n + 1):
        nxt = [0] * (len(counts) + size - 1)
        for k, count in enumerate(counts):
            for added in range(size):
                nxt[k + added] += count
        counts = tuple(nxt)
    return counts


def exact_two_sided_p(n: int, s: int) -> float:
    """``P(|S| >= |s|)`` under H0 for n distinct values."""
    pairs = n * (n - 1) // 2
    if abs(s) > pairs or (pairs - s) % 2:
        raise ValueError(f"S = {s} is impossible for n = {n}")
    tail = sum(count for k, count in enumerate(mahonian(n)) if abs(pairs - 2 * k) >= abs(s))
    return tail / math.factorial(n)
