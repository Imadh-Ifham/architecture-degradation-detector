# Tests for the persistence features (C4-T15, FR-07), hand-computed on fixture and small events.

import copy
from typing import Any

import pytest
from pydantic import BaseModel, Field

from app.components.degradation_scoring.features.persistence import (
    consecutive_releases,
    persistence,
    release_order,
)
from app.domain.degradation_event import AffectedMetric, DegradationEventV2, SeriesValue, Worsening
from tests.components.degradation_scoring.support import load_fixture

PAYLOADS: list[dict[str, Any]] = load_fixture("events/fixture_events.v1.json")
BY_ID = {p["event_id"]: p for p in PAYLOADS if "event_id" in p}
RELEASES = ["v1.0.0", "v1.1.0", "v1.2.0", "v1.3.0", "v1.4.0", "v1.5.0"]


def fixture_event(event_id: str) -> DegradationEventV2:
    return DegradationEventV2.model_validate(copy.deepcopy(BY_ID[event_id]))


def metric(
    values: list[float | None],
    *,
    name: str = "m",
    worsening: Worsening = Worsening.INCREASE,
    releases: list[str] = RELEASES,
) -> AffectedMetric:
    base = fixture_event("DEG-C4FX-R02-0004").affected_metrics[0]
    series = [SeriesValue(release_id=r, value=v) for r, v in zip(releases, values, strict=True)]
    return base.model_copy(update={"metric": name, "worsening": worsening, "series": series})


def event(*metrics: AffectedMetric, end: str = "v1.5.0") -> DegradationEventV2:
    base = fixture_event("DEG-C4FX-R02-0004")
    window = base.window.model_copy(update={"end_release": end})
    return base.model_copy(update={"affected_metrics": list(metrics), "window": window})


def test_fixture_cycle_event() -> None:
    # E01 member_count over v1.2..v1.5 = [-, 3, 4, 4]: present v1.3..v1.5 -> 3 in a row;
    # slope over index 1, 2, 3 = 0.5 per release, mean 11/3 -> 0.5 / (11/3) = 3/22
    ps = persistence(fixture_event("DEG-C4FX-R02-0001"))

    assert ps.consecutive_releases == 3
    assert ps.growth_slope == pytest.approx(3 / 22, abs=1e-12)
    assert ps.growth_metric == "member_count"
    assert ps.growth_slope_available
    assert ps.presence_fallback  # C3 does not send instance_history yet (A2)


def test_fixture_gap_breaks_the_run() -> None:
    # E04 instability = [0.4, -, 0.5, 0.55, 0.6, 0.7]: the v1.1 gap leaves v1.2..v1.5 = 4;
    # x = 0, 2, 3, 4, 5 (gap keeps its index): Sxy = 0.85, Sxx = 14.8, mean y = 0.55
    ps = persistence(fixture_event("DEG-C4FX-R02-0004"))

    assert ps.consecutive_releases == 4
    assert ps.growth_slope == pytest.approx(0.85 / 14.8 / 0.55, abs=1e-12)


def test_fixture_flat_series_has_zero_growth() -> None:
    ps = persistence(fixture_event("DEG-C4FX-R02-0008"))  # member_count 2, 2, 2, 2, 2

    assert ps.consecutive_releases == 5
    assert ps.growth_slope == 0.0
    assert ps.growth_slope_available


def test_units_do_not_decide_the_slope() -> None:
    # size +10 % per release and instability +10 % per release give the same growth
    size = persistence(event(metric([1000, 1100, 1200, 1300, 1400, 1500])))
    instability = persistence(event(metric([0.1, 0.11, 0.12, 0.13, 0.14, 0.15])))

    assert size.growth_slope == pytest.approx(instability.growth_slope, abs=1e-12)
    assert size.growth_slope == pytest.approx(100 / 1250, abs=1e-12)


def test_decreasing_metric_is_flipped_so_positive_means_worsening() -> None:
    falling = metric([10, 9, 8, 7, 6, 5], worsening=Worsening.DECREASE)

    assert persistence(event(falling)).growth_slope == pytest.approx(1 / 7.5, abs=1e-12)


def test_fastest_worsening_metric_is_chosen() -> None:
    slow = metric([10, 10, 11, 11, 12, 12], name="slow")
    fast = metric([1, 2, 3, 4, 5, 6], name="fast")
    improving = metric([6, 5, 4, 3, 2, 1], name="improving")

    ps = persistence(event(slow, improving, fast))

    assert ps.growth_metric == "fast"
    assert ps.growth_slope == pytest.approx(1 / 3.5, abs=1e-12)


def test_improving_only_metric_gives_negative_growth() -> None:
    assert persistence(event(metric([6, 5, 4, 3, 2, 1]))).growth_slope < 0


@pytest.mark.parametrize(
    "values",
    [
        [None, None, None, None, None, 5.0],  # one value
        [None] * 6,  # no values
        [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # mean 0
    ],
)
def test_slope_unavailable(values: list[float | None]) -> None:
    ps = persistence(event(metric(values)))

    assert ps.growth_slope == 0.0
    assert not ps.growth_slope_available
    assert ps.growth_metric is None


def test_missing_detected_release_means_no_run() -> None:
    ps = persistence(event(metric([1, 2, 3, 4, 5, None])))

    assert ps.consecutive_releases == 0


def test_detected_release_outside_the_series() -> None:
    assert persistence(event(metric([1, 2, 3, 4, 5, 6]), end="v9.0.0")).consecutive_releases == 0


def test_single_release() -> None:
    ps = persistence(event(metric([7.0], releases=["v1.5.0"])))

    assert ps.consecutive_releases == 1
    assert not ps.growth_slope_available


def test_release_order_follows_the_series_across_metrics() -> None:
    a = metric([1, 2], releases=["v1.1.0", "v1.3.0"])
    b = metric([1, 2, 3], releases=["v1.1.0", "v1.2.0", "v1.3.0"])

    assert release_order(event(a, b)) == ["v1.1.0", "v1.3.0", "v1.2.0"]
    assert consecutive_releases(["a", "b", "c"], {"a", "c"}, "c") == 1


class HistoryEntry(BaseModel):
    release_id: str


class EventV21(DegradationEventV2):
    # stand-in for C3's proposed V2.1.0 field
    instance_history: list[HistoryEntry] = Field(default_factory=list)


def test_instance_history_is_used_when_c3_sends_it() -> None:
    base = event(metric([1, 2, 3, 4, 5, 6]))
    v21 = EventV21.model_validate(
        {**base.model_dump(), "instance_history": [{"release_id": r} for r in RELEASES[3:]]}
    )

    ps = persistence(v21)

    # every series value is non-null (fallback would say 6), but C3 says present since v1.3
    assert ps.consecutive_releases == 3
    assert not ps.presence_fallback
