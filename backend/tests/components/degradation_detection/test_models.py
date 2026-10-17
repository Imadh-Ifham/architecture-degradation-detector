"""Internal C3 models: strict (extra="forbid"), immutable, and null-preserving."""

import pytest
from pydantic import ValidationError

from app.components.degradation_detection import models
from app.components.degradation_detection.models import (
    AlignMethod,
    AntiPatternInstance,
    EventCandidate,
    InstanceOccurrence,
    InstanceTrack,
    InstanceTransition,
    Lineage,
    LineageEvent,
    LineageEventType,
    LineageMember,
    MetricDef,
    MetricLevel,
    MetricObservation,
    Series,
    SeriesPoint,
    TrackEnd,
    TrendResult,
)
from app.domain.degradation_event import Lifecycle, Scope, Worsening

HASH = "sha256:" + "a" * 64


def trend(**overrides: object) -> TrendResult:
    fields: dict[str, object] = {
        "scope": Scope.INSTANCE,
        "subject_id": "AP-CyclicDependency:a@v1.0.0",
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
        subject_id="AP-CyclicDependency:a@v1.0.0",
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


def member(ordinal: int, element_id: str = "a") -> LineageMember:
    return LineageMember(ordinal=ordinal, release_id=f"v1.{ordinal}.0", element_id=element_id)


def test_lineage_follows_an_element_through_a_rename() -> None:
    lineage = Lineage(
        lineage_id="LIN-order-svc@v1.0.0",
        kind="service",
        members=(member(0, "order-svc"), member(1, "order-service")),
    )
    event = LineageEvent(
        lineage_id=lineage.lineage_id,
        event_type=LineageEventType.RENAME,
        release_id="v1.1.0",
        from_element_ids=("order-svc",),
        to_element_ids=("order-service",),
        method=AlignMethod.ALIAS,
    )

    assert [m.element_id for m in lineage.members] == ["order-svc", "order-service"]
    assert event.similarity is None


@pytest.mark.parametrize("ordinals", [(0, 2), (1, 0), (0, 0)], ids=["gap", "backwards", "repeat"])
def test_lineage_members_must_be_consecutive_releases(ordinals: tuple[int, int]) -> None:
    with pytest.raises(ValidationError, match="consecutive"):
        Lineage(lineage_id="LIN-a@v1.0.0", kind="service", members=tuple(map(member, ordinals)))


def test_lineage_has_at_least_one_member() -> None:
    with pytest.raises(ValidationError):
        Lineage(lineage_id="LIN-a@v1.0.0", kind="service", members=())


def occurrence(ordinal: int, *members: str) -> InstanceOccurrence:
    ids = members or ("a", "b")
    return InstanceOccurrence(
        ordinal=ordinal,
        release_id=f"v1.{ordinal}.0",
        local_instance_id=f"CyclicDependency:{ids[0]}",
        members=ids,
        member_lineages=tuple(f"LIN-{m}@v1.0.0" for m in ids),
        transition=InstanceTransition.INTRODUCED if ordinal == 0 else InstanceTransition.PERSISTED,
    )


def instance_track(*ordinals: int, **overrides: object) -> InstanceTrack:
    fields: dict[str, object] = {
        "track_id": "AP-CyclicDependency:a@v1.0.0",
        "anti_pattern_type": "CyclicDependency",
        "catalog": "universal",
        "scope": Scope.INSTANCE,
        "occurrences": tuple(map(occurrence, ordinals)),
        "end": TrackEnd.OPEN,
        "lifecycle": Lifecycle.PERSISTENT,
    }
    return InstanceTrack.model_validate(fields | overrides)


def test_instance_track_follows_an_instance_through_consecutive_releases() -> None:
    track = instance_track(0, 1, 2)

    assert [o.release_id for o in track.occurrences] == ["v1.0.0", "v1.1.0", "v1.2.0"]
    assert track.ended_at is None


@pytest.mark.parametrize("ordinals", [(0, 2), (1, 0), (0, 0)], ids=["gap", "backwards", "repeat"])
def test_instance_track_occurrences_must_be_consecutive_releases(
    ordinals: tuple[int, int],
) -> None:
    with pytest.raises(ValidationError, match="consecutive"):
        instance_track(*ordinals)


def test_instance_track_has_at_least_one_occurrence() -> None:
    with pytest.raises(ValidationError):
        instance_track()


@pytest.mark.parametrize(
    ("end", "ended_at"),
    [(TrackEnd.OPEN, "v1.1.0"), (TrackEnd.RESOLVED, None), (TrackEnd.UNCHECKED, None)],
)
def test_ended_at_is_set_exactly_when_the_track_has_ended(
    end: TrackEnd, ended_at: str | None
) -> None:
    with pytest.raises(ValidationError, match="ended_at"):
        instance_track(0, end=end, ended_at=ended_at)


def test_occurrence_needs_one_lineage_per_member() -> None:
    fields = occurrence(0).model_dump() | {"member_lineages": ("LIN-a@v1.0.0",)}

    with pytest.raises(ValidationError, match="one lineage id per member"):
        InstanceOccurrence.model_validate(fields)


# --- anti-pattern count metric names (shared by M2, the series builder and M4) ---------------


def test_anti_pattern_count_names_round_trip() -> None:
    assert models.ap_count("CyclicDependency") == "ap_count.CyclicDependency"
    assert models.counted_type("ap_count.CyclicDependency") == "CyclicDependency"
    assert models.counted_type("modularity") is None
    assert models.counted_type(models.AP_INVOLVEMENT_SHARE) is None


def test_anti_pattern_metrics_are_the_counts_and_the_involvement_share() -> None:
    assert models.is_anti_pattern_metric("ap_count.HubLikeElement")
    assert models.is_anti_pattern_metric("ap_involvement_share")
    assert not models.is_anti_pattern_metric("largest_scc_share")
