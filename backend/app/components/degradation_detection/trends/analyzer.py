"""M4 analyzer: test every series of a run, adjust for multiple testing, decide worsening.

Steps (plan Section 4, M4):

1. **Which series are tested.** A metric without a worsening direction (``instability``) is
   never acted on, so it is not tested (``NO_WORSENING_DIRECTION``): every extra test raises
   every q-value of the run. A series with fewer than ``min_releases`` non-null points is too
   short to test (``SERIES_TOO_SHORT``) [D-03]. Both are reported, not dropped silently.
2. **Test.** Mann-Kendall on the non-null values, in order; Sen's slope on the same points with
   their ordinals as the time axis [D-05], so a null release stays a gap in time.
3. **Adjust.** Benjamini-Hochberg over every series tested in this run, one family [D-26].
4. **Decide.** ``is_worsening``: the sign of S is the metric's worsening direction (the p-value
   is two-sided [D-01]; a significant *improvement* is never worsening). ``is_significant``: the
   gated value (q by default [D-02]) is at most alpha. Every result is kept, significant or not.

Which declaration a series is tested under comes from M2 (``DetectionCatalog``): element and
system metrics from the metric registry, instance measures from their detector. An undeclared
metric is a bug, not something to guess a direction for.
"""

from collections.abc import Mapping, Sequence

import structlog

from app.components.degradation_detection.config import TrendConfig
from app.components.degradation_detection.models import (
    DetectionCatalog,
    MetricDef,
    MetricLevel,
    Series,
    TrendResult,
)
from app.components.degradation_detection.trends.mann_kendall import mann_kendall
from app.components.degradation_detection.trends.models import (
    NO_WORSENING_DIRECTION,
    SERIES_TOO_SHORT,
    MannKendallResult,
    SenSlope,
    UntestedSeries,
)
from app.components.degradation_detection.trends.multiple_testing import benjamini_hochberg
from app.components.degradation_detection.trends.sens_slope import sens_slope
from app.domain.degradation_event import Scope, TimeAxis, Worsening

log = structlog.get_logger(__name__)

_LEVEL = {Scope.ELEMENT: MetricLevel.ELEMENT, Scope.SYSTEM: MetricLevel.SYSTEM}


def metric_def(
    series: Series, catalog: DetectionCatalog, track_types: Mapping[str, str]
) -> MetricDef:
    """The declaration a series is tested under. ``track_types``: track id -> anti-pattern type."""
    if series.scope is Scope.INSTANCE:
        try:
            anti_pattern_type = track_types[series.subject_id]
        except KeyError:
            raise KeyError(f"series of {series.subject_id!r} has no instance track") from None
        return catalog.detector(anti_pattern_type).measure(series.metric)
    return catalog.metric(_LEVEL[series.scope], series.metric)


def analyze_series(
    series: Sequence[tuple[Series, MetricDef]], cfg: TrendConfig
) -> tuple[tuple[TrendResult, ...], tuple[UntestedSeries, ...]]:
    """Every testable series tested and adjusted, in input order, and the ones left out."""
    if cfg.time_axis is not TimeAxis.ORDINAL:
        raise NotImplementedError("time_axis 'days' is not built yet; use 'ordinal' [D-05]")

    tested: list[tuple[Series, str, Worsening, MannKendallResult, SenSlope]] = []
    untested: list[UntestedSeries] = []
    for s, definition in series:
        points = [p for p in s.points if p.value is not None]
        worsening = definition.worsening
        if worsening is None:
            untested.append(_untested(s, NO_WORSENING_DIRECTION, len(points)))
            continue
        if len(points) < cfg.min_releases:
            untested.append(_untested(s, SERIES_TOO_SHORT, len(points)))
            continue
        values = [p.value for p in points if p.value is not None]
        mk = mann_kendall(values, exact_below=cfg.exact_below, n_perm=cfg.n_perm, seed=cfg.seed)
        sen = sens_slope([p.ordinal for p in points], values)
        tested.append((s, definition.unit, worsening, mk, sen))

    q_values = benjamini_hochberg([mk.p_value for *_, mk, _ in tested])
    results = tuple(
        _result(s, unit, worsening, mk, sen, q, cfg)
        for (s, unit, worsening, mk, sen), q in zip(tested, q_values, strict=True)
    )
    return results, tuple(untested)


def _untested(s: Series, reason: str, n_points: int) -> UntestedSeries:
    log.info(
        reason,
        reason=reason,
        scope=s.scope.value,
        subject_id=s.subject_id,
        metric=s.metric,
        n_points=n_points,
    )
    return UntestedSeries(
        scope=s.scope, subject_id=s.subject_id, metric=s.metric, reason=reason, n_points=n_points
    )


def _result(
    s: Series,
    unit: str,
    worsening: Worsening,
    mk: MannKendallResult,
    sen: SenSlope,
    q: float,
    cfg: TrendConfig,
) -> TrendResult:
    gated = q if cfg.gate_on == "q" else mk.p_value
    return TrendResult(
        scope=s.scope,
        subject_id=s.subject_id,
        metric=s.metric,
        unit=unit,
        worsening=worsening,
        points=s.points,
        n=mk.n,
        s=mk.s,
        var_s=mk.var_s,
        z=mk.z,
        tau=mk.tau,
        p_value=mk.p_value,
        q_value=q,
        method=mk.method,
        time_axis=cfg.time_axis,
        sen_slope=sen.slope,
        intercept=sen.intercept,
        is_worsening=mk.s > 0 if worsening is Worsening.INCREASE else mk.s < 0,
        is_significant=gated <= cfg.alpha,
    )
