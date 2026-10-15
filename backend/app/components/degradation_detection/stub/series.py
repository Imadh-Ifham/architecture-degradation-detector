"""Bare series with a known answer, for testing Mann-Kendall, Sen's slope and the analyzer.

Each fixture isolates one case the statistics must handle. The time axis is always explicit,
because Sen's slope must use it and never the position of a value in the list.
"""

import random

from app.components.degradation_detection.stub.models import SeriesFixture
from app.components.degradation_detection.stub.noise import kendall_s, trendless_order

INTERCEPT = 3.0
SLOPE = 0.8
FALLING_SLOPE = -0.5


def _line(n: int, slope: float = SLOPE, intercept: float = INTERCEPT) -> list[float]:
    return [round(intercept + slope * t, 6) for t in range(n)]


def _rising_noisy(rng: random.Random) -> list[float]:
    """The line plus noise large enough to break strict order, small enough to keep the trend."""
    n = 12
    while True:
        values = [round(INTERCEPT + SLOPE * t + rng.gauss(0, 0.6), 3) for t in range(n)]
        if 50 <= kendall_s(values) < n * (n - 1) // 2 and len(set(values)) == n:
            return values


def build_series(seed: int) -> tuple[SeriesFixture, ...]:
    outlier = _line(10)
    outlier[6] = 40.0
    gap: list[float | None] = list(_line(10))
    gap[4] = None

    return (
        SeriesFixture(
            name="rising_exact",
            description="x = 3 + 0.8 t with no noise. Sen's slope must be exactly 0.8.",
            time=tuple(range(10)),
            values=tuple(_line(10)),
            expected_trend="increasing",
            planted_slope=SLOPE,
        ),
        SeriesFixture(
            name="rising_noisy",
            description="x = 3 + 0.8 t plus noise: still increasing, no longer monotone.",
            time=tuple(range(12)),
            values=tuple(_rising_noisy(random.Random(f"{seed}:rising-noisy"))),
            expected_trend="increasing",
            planted_slope=SLOPE,
        ),
        SeriesFixture(
            name="rising_outlier",
            description="x = 3 + 0.8 t with one wild value at t = 6. Sen's slope stays 0.8.",
            time=tuple(range(10)),
            values=tuple(outlier),
            expected_trend="increasing",
            planted_slope=SLOPE,
        ),
        SeriesFixture(
            name="rising_gap",
            description=(
                "x = 3 + 0.8 t with a missing value at t = 4. The slope is 0.8 only if the "
                "real time axis is used; re-indexing the remaining points changes it."
            ),
            time=tuple(range(10)),
            values=tuple(gap),
            expected_trend="increasing",
            planted_slope=SLOPE,
        ),
        SeriesFixture(
            name="falling_exact",
            description="x = 10 - 0.5 t. For a metric where lower is worse (modularity).",
            time=tuple(range(10)),
            values=tuple(_line(10, FALLING_SLOPE, 10.0)),
            expected_trend="decreasing",
            planted_slope=FALLING_SLOPE,
        ),
        SeriesFixture(
            name="flat",
            description="A constant. The test is degenerate: p = 1.",
            time=tuple(range(10)),
            values=(5.0,) * 10,
            expected_trend="none",
            planted_slope=0.0,
        ),
        SeriesFixture(
            name="noisy_no_trend",
            description="Ten distinct values in an order with |S| <= 3 of a possible 45.",
            time=tuple(range(10)),
            values=tuple(
                trendless_order(
                    [4.1, 4.4, 4.6, 4.9, 5.0, 5.2, 5.3, 5.5, 5.8, 6.0],
                    random.Random(f"{seed}:noisy-no-trend"),
                )
            ),
            expected_trend="none",
        ),
        SeriesFixture(
            name="step",
            description="Five releases at 2, then five at 6: one jump, heavy ties.",
            time=tuple(range(10)),
            values=(2.0,) * 5 + (6.0,) * 5,
            expected_trend="increasing",
        ),
        SeriesFixture(
            name="with_ties",
            description="Increasing with tied values, n = 12: needs the tie-corrected variance.",
            time=tuple(range(12)),
            values=(1.0, 1.0, 2.0, 2.0, 2.0, 3.0, 3.0, 4.0, 4.0, 4.0, 5.0, 5.0),
            expected_trend="increasing",
        ),
        SeriesFixture(
            name="short_n5",
            description=(
                "Strictly increasing, n = 5: S = 10 and the exact two-sided p is 2/120. "
                "Shorter than trend.min_releases, so the analyzer must skip it."
            ),
            time=tuple(range(5)),
            values=(1.0, 2.0, 3.0, 4.0, 5.0),
            expected_trend="increasing",
            planted_slope=1.0,
        ),
        SeriesFixture(
            name="short_n7",
            description="Strictly increasing, n = 7: one short of trend.min_releases.",
            time=tuple(range(7)),
            values=(2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0),
            expected_trend="increasing",
            planted_slope=0.5,
        ),
    )
