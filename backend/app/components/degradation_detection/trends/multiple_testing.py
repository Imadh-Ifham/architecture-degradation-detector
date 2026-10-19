"""Benjamini-Hochberg false discovery rate control, self-implemented (locked decision 8; pure).

A run tests hundreds of series. At alpha = 0.05 one in twenty trendless series would pass a
p-value gate by chance, so the gate is on q [D-02]: among the series with ``q <= alpha``, the
expected share of false discoveries is at most alpha. The family is every series tested in one
system run, declared before looking at the results [D-26].

``q_(i) = min over j >= i of (m / j) * p_(j)``, capped at 1, for p sorted ascending (rank i).
The running minimum from the top makes q non-decreasing in p (the "step-up").
"""

import math
from collections.abc import Sequence


def benjamini_hochberg(p_values: Sequence[float]) -> tuple[float, ...]:
    """q-values in the order of ``p_values``."""
    if not all(math.isfinite(p) and 0 <= p <= 1 for p in p_values):
        raise ValueError("p-values must be in [0, 1]")
    m = len(p_values)
    q = [0.0] * m
    running = 1.0
    for rank, index in reversed(
        list(enumerate(sorted(range(m), key=lambda i: p_values[i]), start=1))
    ):
        # p * (m / rank), not p * m / rank: the factor is >= 1, so rounding never puts q below p.
        running = min(running, p_values[index] * (m / rank))
        q[index] = running
    return tuple(q)
