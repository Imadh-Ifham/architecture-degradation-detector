"""M4 analyzer: which series are tested, how, and what makes a result worsening and significant."""

from collections.abc import Sequence

import pytest
from structlog.testing import capture_logs

from app.components.degradation_detection.config import TrendConfig
from app.components.degradation_detection.models import (
    DetectionCatalog,
    DetectorInfo,
    MetricDef,
    MetricLevel,
    Series,
    SeriesPoint,
)
from app.components.degradation_detection.trends.analyzer import analyze_series, metric_def
from app.components.degradation_detection.trends.models import (
    NO_WORSENING_DIRECTION,
    SERIES_TOO_SHORT,
)
from app.components.degradation_detection.trends.multiple_testing import benjamini_hochberg
from app.domain.degradation_event import Scope, TestMethod, TimeAxis, Worsening

CFG = TrendConfig()
UP = Worsening.INCREASE
DOWN = Worsening.DECREASE

RISING = [float(v) for v in range(10)]
FALLING = RISING[::-1]
FLAT = [5.0] * 10
# A wobbly climb: p = 0.0064 on its own, q = 0.064 next to nine flat series.
WEAK = [2.0, 1.0, 3.0, 2.0, 4.0, 3.0, 5.0, 4.0, 6.0, 5.0]


def series(
    values: Sequence[float | None],
    *,
    metric: str = "fan_in",
    subject: str = "LIN-a@v1.0.0",
    scope: Scope = Scope.ELEMENT,
    start: int = 0,
) -> Series:
    return Series(
        scope=scope,
        subject_id=subject,
        metric=metric,
        points=tuple(
            SeriesPoint(ordinal=start + i, release_id=f"v1.{start + i}.0", value=v)
            for i, v in enumerate(values)
        ),
    )


def defn(worsening: Worsening | None = UP, name: str = "fan_in") -> MetricDef:
    return MetricDef(name=name, level=MetricLevel.ELEMENT, unit="count", worsening=worsening)


def run(
    *pairs: tuple[Series, MetricDef], cfg: TrendConfig = CFG
) -> tuple[list[tuple[str, str]], dict[str, float], list[str]]:
    """(subject, metric) of each result, q by subject, and untested reasons."""
    results, untested = analyze_series(pairs, cfg)
    return (
        [(r.subject_id, r.metric) for r in results],
        {r.subject_id: r.q_value for r in results},
        [u.reason for u in untested],
    )


# --- one series ---------------------------------------------------------------------------


def test_rising_series_of_an_increase_metric_is_worsening_and_significant() -> None:
    [result], untested = analyze_series([(series(RISING), defn(UP))], CFG)

    assert untested == ()
    assert (result.n, result.s, result.method) == (10, 45, TestMethod.NORMAL)
    assert result.tau == 1.0
    assert result.q_value == result.p_value  # a family of one
    assert result.sen_slope == 1.0
    assert result.intercept == 0.0
    assert result.time_axis is TimeAxis.ORDINAL
    assert (result.unit, result.worsening) == ("count", UP)
    assert result.is_worsening
    assert result.is_significant


@pytest.mark.parametrize(
    ("worsening", "values", "expected"),
    [
        (UP, RISING, True),
        (UP, FALLING, False),
        (DOWN, RISING, False),
        (DOWN, FALLING, True),
        (UP, FLAT, False),
        (DOWN, FLAT, False),
    ],
    ids=["up-rising", "up-falling", "down-rising", "down-falling", "up-flat", "down-flat"],
)
def test_worsening_means_the_sign_of_s_is_the_metric_direction(
    worsening: Worsening, values: list[float], expected: bool
) -> None:
    [result], _ = analyze_series([(series(values), defn(worsening))], CFG)

    assert result.is_worsening is expected


def test_improving_series_is_significant_but_not_worsening() -> None:
    [result], _ = analyze_series([(series(FALLING), defn(UP))], CFG)

    assert result.is_significant
    assert not result.is_worsening


def test_constant_series_is_tested_degenerate_and_never_significant() -> None:
    [result], _ = analyze_series([(series(FLAT), defn(UP))], CFG)

    assert (result.method, result.p_value, result.sen_slope) == (TestMethod.DEGENERATE, 1.0, 0.0)
    assert not result.is_significant


def test_short_series_with_ties_uses_the_seeded_permutation_test() -> None:
    values = [1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 3.0, 4.0]

    [first], _ = analyze_series([(series(values), defn())], CFG)
    [again], _ = analyze_series([(series(values), defn())], CFG)

    assert first.method is TestMethod.PERMUTATION
    assert first == again


def test_tie_free_series_below_exact_below_uses_the_exact_test() -> None:
    [result], _ = analyze_series([(series(RISING[:8]), defn())], CFG)

    assert result.method is TestMethod.EXACT
    assert result.p_value == pytest.approx(2 / 40320)


# --- what is not tested -------------------------------------------------------------------


@pytest.mark.parametrize(
    "values",
    [RISING[:7], [0.0, 1.0, None, 3.0, None, 5.0, 6.0, None, 8.0, 9.0]],
    ids=["seven-points", "ten-points-three-null"],
)
def test_series_with_fewer_than_min_releases_non_null_points_is_not_tested(
    values: list[float | None],
) -> None:
    with capture_logs() as logs:
        results, [untested] = analyze_series([(series(values), defn())], CFG)

    assert results == ()
    assert (untested.reason, untested.n_points) == (SERIES_TOO_SHORT, 7)
    assert [e["reason"] for e in logs] == [SERIES_TOO_SHORT]


def test_min_releases_comes_from_config() -> None:
    results, untested = analyze_series(
        [(series(RISING[:7]), defn())], TrendConfig(min_releases=7, exact_below=10)
    )

    assert len(results) == 1
    assert untested == ()


def test_metric_without_a_direction_is_not_tested_and_stays_out_of_the_family() -> None:
    """instability supports detectors only; testing it would only make every q larger."""
    with capture_logs() as logs:
        tested, q, reasons = run(
            (series(RISING, metric="instability", subject="x"), defn(None, "instability")),
            (series(WEAK, subject="weak"), defn()),
        )

    assert tested == [("weak", "fan_in")]
    assert reasons == [NO_WORSENING_DIRECTION]
    assert NO_WORSENING_DIRECTION in [e["reason"] for e in logs]
    [alone], _ = analyze_series([(series(WEAK, subject="weak"), defn())], CFG)
    assert q["weak"] == alone.q_value  # the instability series did not join the family


# --- nulls and the time axis --------------------------------------------------------------


def test_null_points_are_dropped_and_their_gap_stays_in_time() -> None:
    """Values 2t with t = 4 missing: Sen's slope is 2 per release, not stretched by re-indexing."""
    values: list[float | None] = [2.0 * t for t in range(10)]
    values[4] = None

    [result], _ = analyze_series([(series(values), defn())], CFG)

    assert result.n == 9
    assert result.sen_slope == 2.0
    assert result.intercept == 0.0
    assert result.points == series(values).points  # the whole series, null kept


def test_series_that_starts_late_keeps_its_ordinals() -> None:
    [result], _ = analyze_series([(series(RISING, start=3), defn())], CFG)

    assert result.sen_slope == 1.0
    assert result.intercept == -3.0  # value 0 at ordinal 3


# --- the family: Benjamini-Hochberg across every tested series ---------------------------


def test_q_values_are_benjamini_hochberg_over_every_tested_series_in_input_order() -> None:
    pairs = [
        (series(WEAK, subject="weak"), defn()),
        (series(RISING, subject="rising"), defn()),
        (series(FLAT, subject="flat"), defn()),
    ]

    results, _ = analyze_series(pairs, CFG)

    assert [r.subject_id for r in results] == ["weak", "rising", "flat"]
    assert [r.q_value for r in results] == list(benjamini_hochberg([r.p_value for r in results]))


def test_gate_on_q_rejects_what_gate_on_p_accepts() -> None:
    pairs = [(series(WEAK, subject="weak"), defn())] + [
        (series(FLAT, subject=f"flat{i}"), defn()) for i in range(9)
    ]

    on_q, _ = analyze_series(pairs, CFG)
    on_p, _ = analyze_series(pairs, TrendConfig(gate_on="p"))

    assert on_q[0].p_value <= CFG.alpha < on_q[0].q_value
    assert not on_q[0].is_significant
    assert on_p[0].is_significant


def test_alpha_comes_from_config() -> None:
    [strict], _ = analyze_series([(series(WEAK), defn())], TrendConfig(alpha=0.001))

    assert strict.p_value > 0.001
    assert not strict.is_significant


def test_no_series_gives_no_results() -> None:
    assert analyze_series([], CFG) == ((), ())


def test_days_time_axis_is_not_built_yet() -> None:
    with pytest.raises(NotImplementedError, match="days"):
        analyze_series([(series(RISING), defn())], TrendConfig(time_axis=TimeAxis.DAYS))


# --- which declaration a series is tested under ------------------------------------------

CYCLE = DetectorInfo(
    anti_pattern_type="CyclicDependency",
    catalog="universal",
    scope=Scope.INSTANCE,
    driving_metrics=("scc_size",),
    instance_measures=(
        MetricDef(name="member_count", level=MetricLevel.INSTANCE, unit="count", worsening=UP),
    ),
)
CATALOG = DetectionCatalog(
    metrics=(
        defn(),
        MetricDef(name="modularity", level=MetricLevel.SYSTEM, unit="modularity", worsening=DOWN),
    ),
    detectors=(CYCLE,),
)
TRACK = "AP-CyclicDependency:a@v1.1.0"


def test_element_and_system_series_take_the_registry_declaration() -> None:
    assert metric_def(series(RISING), CATALOG, {}) == defn()
    system = series(RISING, scope=Scope.SYSTEM, subject="tiny", metric="modularity")
    assert metric_def(system, CATALOG, {}).worsening is DOWN


def test_instance_series_takes_its_detectors_measure_declaration() -> None:
    s = series(RISING, scope=Scope.INSTANCE, subject=TRACK, metric="member_count")

    assert metric_def(s, CATALOG, {TRACK: "CyclicDependency"}) == CYCLE.instance_measures[0]


def test_undeclared_metric_is_an_error_not_a_guess() -> None:
    with pytest.raises(KeyError, match="not declared"):
        metric_def(series(RISING, metric="mystery"), CATALOG, {})
    with pytest.raises(KeyError, match="not an instance measure"):
        s = series(RISING, scope=Scope.INSTANCE, subject=TRACK, metric="degree")
        metric_def(s, CATALOG, {TRACK: "CyclicDependency"})
    with pytest.raises(KeyError, match="no instance track"):
        s = series(RISING, scope=Scope.INSTANCE, subject="AP-gone", metric="member_count")
        metric_def(s, CATALOG, {})
