# Tests for the normaliser: hand-computed bounds and values,
# small-n and sparse fallbacks, calibration freeze and its save/load.

from collections.abc import Sequence
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from app.components.degradation_scoring.scoring_engine.errors import CalibrationError
from app.components.degradation_scoring.scoring_engine.models import (
    Calibration,
    FeatureBounds,
    NormalisedSet,
    RawEvent,
)
from app.components.degradation_scoring.scoring_engine.normalizer import (
    calibration_filename,
    criterion_value,
    fit_bounds,
    load_calibration,
    normalise,
    save_calibration,
    scale,
)
from app.domain.severity_report import Dimension, NormalizationMode

BR, EH, AV, PS = (
    Dimension.BLAST_RADIUS,
    Dimension.HOTSPOT,
    Dimension.ADR_VIOLATION,
    Dimension.PERSISTENCE,
)
WEIGHTS = {
    BR: {"br_fan_in_ratio": 0.25, "br_pagerank": 0.25, "br_betweenness": 0.25, "br_depth": 0.25},
    EH: {
        "eh_churn_decayed": 0.25,
        "eh_authors": 0.25,
        "eh_coupling": 0.25,
        "eh_bugfix_ratio": 0.25,
    },
    PS: {"ps_consecutive_releases": 0.7, "ps_growth_slope": 0.3},
}


def event(
    event_id: str,
    *,
    fan: float = 0.0,
    pagerank: float = 0.0,
    betweenness: float = 0.0,
    depth: float = 0.0,
    releases: float = 0.0,
    slope: float = 0.0,
    coupling: float | None = None,
    av: float | None = None,
) -> RawEvent:
    values = {
        "br_fan_in_ratio": fan,
        "br_pagerank": pagerank,
        "br_betweenness": betweenness,
        "br_depth": depth,
        "ps_consecutive_releases": releases,
        "ps_growth_slope": slope,
    }
    if coupling is not None:
        values |= {
            "eh_churn_decayed": 10.0,
            "eh_authors": 2.0,
            "eh_coupling": coupling,
            "eh_bugfix_ratio": 0.0,
        }
    if av is not None:
        values["av_weight"] = av
    return RawEvent(event_id=event_id, values=values)


def norm(
    events: Sequence[RawEvent],
    active: Sequence[Dimension] = (BR, PS),
    system_id: str = "shop",
    calibration: Calibration | None = None,
) -> NormalisedSet:
    return normalise(
        events,
        active,
        system_id=system_id,
        release_id="v2",
        weights=WEIGHTS,
        lower_percentile=5.0,
        upper_percentile=95.0,
        small_n_threshold=10,
        calibration=calibration,
    )


def spread(n: int, coupling: float | None = None, av: float | None = None) -> list[RawEvent]:
    # n events whose features grow with their index, so every range is non-zero
    return [
        event(
            f"E{i:02d}",
            fan=i / n,
            pagerank=i / 100,
            betweenness=i / 200,
            depth=i,
            releases=i,
            slope=i / 50,
            coupling=coupling,
            av=av,
        )
        for i in range(n)
    ]


def test_one_extreme_value_does_not_flatten_the_others() -> None:
    # 1..39 and 1000: P5 at position 0.05*39 = 1.95 -> 2.95; P95 at 37.05 -> 38.05
    values = [float(v) for v in range(1, 40)] + [1000.0]
    bounds = fit_bounds(values, robust=True, lower_percentile=5.0, upper_percentile=95.0)
    assert bounds.lower == pytest.approx(2.95)
    assert bounds.upper == pytest.approx(38.05)
    assert scale(20.0, bounds) == pytest.approx(17.05 / 35.1)  # 0.4858
    assert scale(1000.0, bounds) == 1.0
    assert scale(1.0, bounds) == 0.0
    plain = fit_bounds(values, robust=False, lower_percentile=5.0, upper_percentile=95.0)
    assert scale(20.0, plain) == pytest.approx(19 / 999)  # 0.019: what winsorising prevents


def test_small_n_uses_plain_min_max_and_hand_computed_criteria() -> None:
    # min-max: B = BR (0.5 + 0.25 + 1 + 1) / 4, PS 0.7 * 0.5 + 0.3 * 1
    result = norm(
        [
            event("A", fan=0.0, pagerank=0.1, betweenness=0.0, depth=1, releases=1),
            event("B", fan=0.5, pagerank=0.2, betweenness=0.4, depth=3, releases=3, slope=0.2),
            event("C", fan=1.0, pagerank=0.5, betweenness=0.2, depth=2, releases=5, slope=-0.2),
        ]
    )
    assert result.mode is NormalizationMode.MINMAX_SMALL_N
    assert not result.frozen
    a, b, c = result.events
    assert b.features["br_pagerank"] == pytest.approx(0.25)
    assert b.criteria[BR] == pytest.approx(0.6875)
    assert b.criteria[PS] == pytest.approx(0.65)
    assert c.criteria[BR] == pytest.approx(0.75)
    assert c.criteria[PS] == pytest.approx(0.7)
    assert a.criteria[BR] == pytest.approx(0.0)
    assert a.criteria[PS] == pytest.approx(0.15)
    assert result.calibration.bounds["ps_growth_slope"] == FeatureBounds(lower=-0.2, upper=0.2)


def test_mode_switches_to_robust_at_the_threshold() -> None:
    assert norm(spread(9)).mode is NormalizationMode.MINMAX_SMALL_N
    robust = norm(spread(10))
    assert robust.mode is NormalizationMode.ROBUST_MINMAX
    # depth 0..9: P5 = 0.45, P95 = 8.55
    assert robust.calibration.bounds["br_depth"].lower == pytest.approx(0.45)
    assert robust.calibration.bounds["br_depth"].upper == pytest.approx(8.55)


def test_zero_range_gives_one_half_and_a_warning() -> None:
    with capture_logs() as logs:
        result = norm([event("A", depth=3), event("B", depth=3, fan=1.0)])
    assert [e.features["br_depth"] for e in result.events] == [0.5, 0.5]
    warned = {log["feature"] for log in logs if log.get("reason") == "zero_range"}
    assert "br_depth" in warned
    assert "br_fan_in_ratio" not in warned


def test_sparse_feature_falls_back_to_min_max_and_keeps_its_signal() -> None:
    # 25 events, one with coupling 3: P5 = P95 = 0, so §5.5 alone would give all 0.5
    events = spread(25, coupling=0)
    events[7] = event("E07", fan=0.3, depth=7, releases=7, coupling=3)
    with capture_logs() as logs:
        result = norm(events, (BR, EH, PS))
    assert result.mode is NormalizationMode.ROBUST_MINMAX
    bounds = result.calibration.bounds["eh_coupling"]
    assert (bounds.lower, bounds.upper, bounds.fallback) == (0.0, 3.0, "sparse_minmax")
    coupling = [e.features["eh_coupling"] for e in result.events]
    assert coupling[7] == 1.0
    assert sum(coupling) == 1.0
    assert result.calibration.bounds["eh_authors"].fallback is None  # really constant
    assert any(log.get("reason") == "sparse_minmax" for log in logs)


def test_frozen_bounds_keep_existing_values_on_a_changed_event_set() -> None:
    first = norm(spread(12))
    extreme = event("X", fan=1.0, pagerank=5.0, betweenness=1.0, depth=99, releases=40, slope=9)
    second = norm([*spread(12), extreme], calibration=first.calibration)
    assert second.frozen
    assert second.mode is first.mode
    assert second.events[:12] == first.events
    assert second.events[12].features["br_depth"] == 1.0  # clipped to the frozen upper bound
    refitted = norm([*spread(12), extreme])
    assert refitted.events[:12] != first.events  # what freezing protects against


def test_saved_calibration_loads_to_identical_values(tmp_path: Path) -> None:
    first = norm(spread(12, coupling=1), (BR, EH, PS))
    path = tmp_path / "shop" / calibration_filename("shop")
    save_calibration(first.calibration, path)
    assert path.name == "calibration_shop.json"
    loaded = load_calibration(path)
    assert loaded == first.calibration
    again = norm(spread(12, coupling=1), (BR, EH, PS), calibration=loaded)
    assert again.events == first.events


def test_unusable_calibration_raises(tmp_path: Path) -> None:
    calibration = norm(spread(3)).calibration
    with pytest.raises(CalibrationError, match="system 'shop'"):
        norm(spread(3), system_id="other", calibration=calibration)
    with pytest.raises(CalibrationError, match="eh_churn_decayed"):
        norm(spread(3, coupling=0), (BR, EH, PS), calibration=calibration)
    garbage = tmp_path / "bad.json"
    garbage.write_text("{not json", encoding="utf-8")
    with pytest.raises(CalibrationError):
        load_calibration(garbage)
    with pytest.raises(CalibrationError):
        load_calibration(tmp_path / "missing.json")


def test_calibration_with_extra_features_still_applies() -> None:
    with_hotspot = norm(spread(3, coupling=1), (BR, EH, PS)).calibration
    result = norm(spread(3), calibration=with_hotspot)
    assert result.active_criteria == [BR, PS]


def test_av_passes_through_unscaled() -> None:
    # a weak superseded ADR (0.2) stays 0.2; min-max would make it 1.0
    result = norm([event("A", av=0.2), event("B", av=0.0)], (BR, AV, PS))
    assert result.active_criteria == [BR, AV, PS]
    assert [e.criteria[AV] for e in result.events] == [0.2, 0.0]
    assert result.events[0].features["av_weight"] == 0.2
    assert "av_weight" not in result.calibration.bounds


def test_inactive_criteria_are_left_out() -> None:
    result = norm(spread(3, coupling=2, av=1.0))
    assert result.active_criteria == [BR, PS]
    assert set(result.events[0].criteria) == {BR, PS}
    assert not any(key.startswith(("eh_", "av_")) for key in result.events[0].features)
    assert not any(key.startswith(("eh_", "av_")) for key in result.calibration.bounds)


def test_criteria_come_out_in_report_order() -> None:
    result = norm(spread(3, coupling=1, av=0.5), (PS, AV, EH, BR))
    assert result.active_criteria == [BR, EH, AV, PS]
    assert list(result.events[1].criteria) == [BR, EH, AV, PS]
    assert all(0.0 <= v <= 1.0 for e in result.events for v in e.features.values())


def test_missing_value_for_an_active_criterion_is_an_error() -> None:
    with pytest.raises(ValueError, match="eh_churn_decayed"):
        norm([event("A")], (BR, EH, PS))
    with pytest.raises(ValueError, match="av_weight"):
        norm([event("A")], (BR, AV, PS))


def test_empty_input_and_input_order() -> None:
    empty = norm([])
    assert empty.events == []
    assert empty.calibration.bounds == {}
    assert empty.mode is NormalizationMode.MINMAX_SMALL_N
    ids = [e.event_id for e in norm(list(reversed(spread(4)))).events]
    assert ids == ["E03", "E02", "E01", "E00"]


def test_criterion_value_is_a_weighted_mean() -> None:
    assert criterion_value({"a": 1.0, "b": 0.0}, {"a": 0.7, "b": 0.3}) == pytest.approx(0.7)
    assert criterion_value({"a": 1.0, "b": 0.0}, {"a": 2.0, "b": 2.0}) == pytest.approx(0.5)
    with pytest.raises(ValueError, match="more than 0"):
        criterion_value({"a": 1.0}, {"a": 0.0})
