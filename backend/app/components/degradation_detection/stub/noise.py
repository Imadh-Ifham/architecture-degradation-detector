"""Noise that is guaranteed to have no trend.

A random walk, or even independent noise, shows a significant Mann-Kendall trend by chance in a
share of seeds. A fixture that is supposed to mean "no trend" cannot depend on luck, so the
values are shuffled until Kendall's S is close to zero.
"""

import random
from collections.abc import Callable, Sequence

MAX_ABS_S = 3


def kendall_s(values: Sequence[float]) -> int:
    """Mann-Kendall S: pairs that go up minus pairs that go down."""
    return sum((b > a) - (b < a) for i, a in enumerate(values) for b in values[i + 1 :])


def trendless_order[T: (int, float)](
    values: Sequence[T],
    rng: random.Random,
    accept: Callable[[list[T]], bool] = lambda _: True,
) -> list[T]:
    """Return ``values`` in a random order with ``|S| <= MAX_ABS_S`` that ``accept`` agrees to."""
    order = list(values)
    while True:
        rng.shuffle(order)
        if abs(kendall_s(order)) <= MAX_ABS_S and accept(order):
            return order
