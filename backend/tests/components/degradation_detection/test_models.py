"""Internal C3 models: strict (extra="forbid"), immutable, and null-preserving."""

import pytest
from pydantic import ValidationError

from app.components.degradation_detection import models
from app.components.degradation_detection.models import (
    AntiPatternInstance,
    EventCandidate,
    MetricDef,
    MetricLevel,
    MetricObservation,
    Series,
    SeriesPoint,
    TrendResult,
)
from app.domain.degradation_event import Scope, Worsening

HASH = "sha256:" + "a" * 64


def trend(**overrides: object) -> TrendResult:
    fields: dict[str, object] = {
        "scope": Scope.INSTANCE,
        "subject_id": "AP-CYC-0001",
        "metric": "member_count",
        "n": 9,
        "s": 30,
        "tau": 0.83,
        "p_value": 0.0012,
        "method": models.TestMethod.EXACT,
    }
    return TrendResult.model_validate(fields | overrides)


def test_every_internal_model_is_strict_and_frozen() -> None:
    internal = [
        cls
        for cls in vars(models).values()
        if isinstance(cls, type)
        and issubclass(cls, models.InternalModel)
        and cls.__module__ == models.__name__
    ]

    assert len(internal) > 5
    for cls in internal:
        assert cls.model_config.get("extra") == "forbid", cls.__name__
        assert cls.model_config.get("frozen") is True, cls.__name__


def test_null_observation_stays_null() -> None:
    isolated = MetricObservation(release_id="v1", element_id="a", metric="instability", value=None)
    system = MetricObservation(release_id="v1", element_id=None, metric="modularity", value=0.0)

    assert isolated.value is None
    assert system.value == 0.0


def test_metric_def_may_have_no_worsening_direction() -> None:
    fan_in = MetricDef(
        name="fan_in", level=MetricLevel.ELEMENT, unit="elements", worsening=Worsening.INCREASE
    )
    instability = MetricDef(name="instability", level=MetricLevel.ELEMENT, unit="ratio")

    assert fan_in.worsening is Worsening.INCREASE
    assert instability.worsening is None


def test_series_keeps_nulls_and_the_explicit_ordinals() -> None:
    series = Series(
        scope=Scope.ELEMENT,
        subject_id="LIN-0001",
        metric="size_rz",
        points=(
            SeriesPoint(ordinal=0, release_id="v1.0.0", value=1.5),
            SeriesPoint(ordinal=2, release_id="v1.2.0", value=None),
        ),
    )

    assert [p.ordinal for p in series.points] == [0, 2]
    assert series.points[1].value is None


@pytest.mark.parametrize("ordinals", [(1, 0), (0, 0)])
def test_series_ordinals_must_strictly_increase(ordinals: tuple[int, int]) -> None:
    points = tuple(
        SeriesPoint(ordinal=o, release_id=f"r{i}", value=1.0) for i, o in enumerate(ordinals)
    )

    with pytest.raises(ValidationError, match="strictly increasing"):
        Series(scope=Scope.SYSTEM, subject_id="shopfront", metric="modularity", points=points)


def test_anti_pattern_instance_carries_members_and_measures() -> None:
    instance = AntiPatternInstance(
        release_id="v1.1.0",
        local_instance_id="CyclicDependency#0",
        anti_pattern_type="CyclicDependency",
        catalog="universal",
        scope=Scope.INSTANCE,
        members=("order", "payment", "inventory"),
        measures={"member_count": 3, "internal_edge_count": None},
    )

    assert instance.measures["internal_edge_count"] is None


def test_trend_result_before_and_after_multiple_testing() -> None:
    untested = trend()
    adjusted = trend(q_value=0.0081, is_worsening=True, is_significant=True)

    assert untested.q_value is None
    assert untested.is_significant is False
    assert adjusted.is_significant is True


def test_event_candidate_groups_the_trends_behind_one_event() -> None:
    candidate = EventCandidate(
        event_key=HASH,
        scope=Scope.INSTANCE,
        subject_id="AP-CYC-0001",
        anti_pattern_type="CyclicDependency",
        catalog="universal",
        start_release="v1.1.0",
        end_release="v1.9.0",
        n_releases=9,
        low_confidence_releases=("v1.5.0",),
        trends=(trend(q_value=0.0081, is_worsening=True, is_significant=True),),
        trend_strength=0.83,
    )

    assert candidate.trends[0].metric == "member_count"
