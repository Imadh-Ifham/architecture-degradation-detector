"""M3 series builder: one table of series in three scopes, M4's only input (T-10)."""

from collections.abc import Iterable, Mapping, Sequence

import pytest
from structlog.testing import capture_logs

from app.components.degradation_detection.config import C3Config
from app.components.degradation_detection.detection import DetectionService
from app.components.degradation_detection.ingestion import IngestService
from app.components.degradation_detection.ingestion.models import RawPackage
from app.components.degradation_detection.models import (
    AntiPatternInstance,
    MetricObservation,
    ReleaseDetection,
    Series,
    Timeline,
)
from app.components.degradation_detection.stub import StubService
from app.components.degradation_detection.tracking import TrackingService
from app.components.degradation_detection.tracking.models import (
    SERIES_DETECTOR_GAP,
    TrackingResult,
)
from app.domain.degradation_event import Scope
from tests.components.degradation_detection.fakes import FixedClock, InMemoryReleaseRepository
from tests.components.degradation_detection.tracking.timelines import (
    el,
    instance,
    rel,
    timeline,
)

CFG = C3Config()
CYC = "CyclicDependency"
SP = "SharedPersistence"

# (element id or None for the system, metric) -> value
Values = Mapping[tuple[str | None, str], float | None]


def det(
    release_id: str,
    values: Values,
    *,
    run: Sequence[str] = (),
    instances: Iterable[AntiPatternInstance] = (),
) -> ReleaseDetection:
    return ReleaseDetection(
        release_id=release_id,
        observations=tuple(
            MetricObservation(release_id=release_id, element_id=e, metric=metric, value=value)
            for (e, metric), value in values.items()
        ),
        instances=tuple(i.model_copy(update={"release_id": release_id}) for i in instances),
        detectors_run=tuple(run),
    )


def dets(
    tl: Timeline,
    *per_release: Values,
    run: Sequence[str] = (),
    instances: Iterable[AntiPatternInstance] = (),
) -> tuple[ReleaseDetection, ...]:
    """One detection per release, with the same detectors run and instances in each."""
    found = tuple(instances)
    return tuple(
        det(entry.release.release_id, values, run=run, instances=found)
        for entry, values in zip(tl.entries, per_release, strict=True)
    )


def build(tl: Timeline, detections: Sequence[ReleaseDetection]) -> tuple[Series, ...]:
    return TrackingService(CFG).track(tl, detections).series


def points(series: Series) -> list[tuple[int, str, float | None]]:
    return [(p.ordinal, p.release_id, p.value) for p in series.points]


def one(series: Iterable[Series], scope: Scope, subject: str, metric: str) -> Series:
    [found] = [s for s in series if (s.scope, s.subject_id, s.metric) == (scope, subject, metric)]
    return found


def keys(series: Iterable[Series]) -> list[tuple[str, str, str]]:
    return [(s.scope.value, s.subject_id, s.metric) for s in series]


def reasons(logs: list[dict[str, object]]) -> list[object]:
    return [entry.get("reason") for entry in logs if "reason" in entry]


# --- ELEMENT scope ------------------------------------------------------------------------------


def test_element_series_follows_its_lineage_through_a_rename() -> None:
    tl = timeline(rel("v1.0.0", ["order-svc"]), rel("v1.1.0", [el("order", aliases=["order-svc"])]))

    series = build(tl, dets(tl, {("order-svc", "size"): 100.0}, {("order", "size"): 150.0}))

    assert keys(series) == [("ELEMENT", "LIN-order-svc@v1.0.0", "size")]
    assert points(series[0]) == [(0, "v1.0.0", 100.0), (1, "v1.1.0", 150.0)]


def test_null_value_stays_a_null_point_in_its_place() -> None:
    tl = timeline(rel("v1.0.0", ["a"]), rel("v1.1.0", ["a"]), rel("v1.2.0", ["a"]))

    [series] = build(
        tl,
        dets(tl, {("a", "size_rz"): 1.0}, {("a", "size_rz"): None}, {("a", "size_rz"): 3.0}),
    )

    assert points(series) == [(0, "v1.0.0", 1.0), (1, "v1.1.0", None), (2, "v1.2.0", 3.0)]


def test_series_starts_when_its_element_first_exists() -> None:
    tl = timeline(rel("v1.0.0", ["a"]), rel("v1.1.0", ["a", "b"]))

    series = build(tl, dets(tl, {("a", "size"): 1.0}, {("a", "size"): 1.0, ("b", "size"): 2.0}))

    assert points(one(series, Scope.ELEMENT, "LIN-b@v1.1.0", "size")) == [(1, "v1.1.0", 2.0)]


def test_kind_change_starts_a_new_series() -> None:
    tl = timeline(rel("v1.0.0", [el("a", kind="service")]), rel("v1.1.0", [el("a", kind="lib")]))

    series = build(tl, dets(tl, {("a", "size"): 1.0}, {("a", "size"): 9.0}))

    assert keys(series) == [
        ("ELEMENT", "LIN-a@v1.0.0", "size"),
        ("ELEMENT", "LIN-a@v1.1.0", "size"),
    ]
    assert [len(s.points) for s in series] == [1, 1]


def test_metric_missing_from_one_release_is_a_null_point() -> None:
    tl = timeline(rel("v1.0.0", ["a"]), rel("v1.1.0", ["a"]))

    [series] = build(tl, dets(tl, {("a", "c1.lcom"): 4.0}, {}))

    assert points(series) == [(0, "v1.0.0", 4.0), (1, "v1.1.0", None)]


# --- INSTANCE scope -----------------------------------------------------------------------------


def test_instance_series_has_one_point_per_occurrence_of_its_track() -> None:
    tl = timeline(rel("v1.0.0", ["a", "b", "c"]), rel("v1.1.0", ["a", "b", "c"]))
    detections = (
        det("v1.0.0", {}, run=[CYC], instances=[instance(CYC, "a", "b")]),
        det("v1.1.0", {}, run=[CYC], instances=[instance(CYC, "a", "b", "c")]),
    )

    series = build(tl, detections)

    assert keys(series) == [("INSTANCE", "AP-CyclicDependency:a@v1.0.0", "member_count")]
    assert points(series[0]) == [(0, "v1.0.0", 2.0), (1, "v1.1.0", 3.0)]


def test_instance_measure_missing_from_one_occurrence_is_a_null_point() -> None:
    tl = timeline(rel("v1.0.0", ["a", "b"]), rel("v1.1.0", ["a", "b"]))
    with_extra = instance(CYC, "a", "b").model_copy(
        update={"measures": {"member_count": 2.0, "internal_edge_count": 2.0}}
    )
    detections = (
        det("v1.0.0", {}, run=[CYC], instances=[with_extra]),
        det("v1.1.0", {}, run=[CYC], instances=[instance(CYC, "a", "b")]),
    )

    series = build(tl, detections)

    edges = one(series, Scope.INSTANCE, "AP-CyclicDependency:a@v1.0.0", "internal_edge_count")
    assert points(edges) == [(0, "v1.0.0", 2.0), (1, "v1.1.0", None)]


def test_element_and_system_scope_tracks_get_no_instance_series() -> None:
    """Their trend is the lineage's or the system's series; a copy would be tested twice."""
    tl = timeline(rel("v1.0.0", ["a", "b"]))
    hub = instance("HubLikeElement", "a", scope=Scope.ELEMENT)
    mud = instance("BigBallOfMud", "a", "b", scope=Scope.SYSTEM, key="system")

    series = build(
        tl, (det("v1.0.0", {}, run=["HubLikeElement", "BigBallOfMud"], instances=[hub, mud]),)
    )

    assert series == ()


# --- SYSTEM scope -------------------------------------------------------------------------------


def test_system_series_covers_every_release() -> None:
    tl = timeline(rel("v1.0.0", ["a"]), rel("v1.1.0", ["b"]), rel("v1.2.0", ["c"]))

    [series] = build(
        tl,
        dets(
            tl,
            {(None, "modularity"): 0.5},
            {(None, "modularity"): None},
            {(None, "modularity"): 0.3},
        ),
    )

    assert (series.scope, series.subject_id) == (Scope.SYSTEM, "tiny")
    assert points(series) == [(0, "v1.0.0", 0.5), (1, "v1.1.0", None), (2, "v1.2.0", 0.3)]


def four_releases() -> Timeline:
    return timeline(*(rel(f"v1.{k}.0", ["a"]) for k in range(4)))


def test_count_series_breaks_where_its_detector_did_not_run_and_keeps_the_last_stretch() -> None:
    tl = four_releases()
    count = "ap_count.SharedPersistence"
    detections = (
        det("v1.0.0", {(None, count): 1.0}, run=[SP]),
        det("v1.1.0", {(None, count): None}, run=[]),  # no datastore_access in this release
        det("v1.2.0", {(None, count): 2.0}, run=[SP]),
        det("v1.3.0", {(None, count): 3.0}, run=[SP]),
    )

    with capture_logs() as logs:
        [series] = build(tl, detections)

    assert points(series) == [(2, "v1.2.0", 2.0), (3, "v1.3.0", 3.0)]
    assert reasons(logs) == [SERIES_DETECTOR_GAP]
    [gap] = [entry for entry in logs if entry.get("reason") == SERIES_DETECTOR_GAP]
    assert (gap["metric"], gap["points_dropped"]) == (count, 1)


def test_count_series_ends_where_its_detector_stopped_running() -> None:
    tl = four_releases()
    count = "ap_count.SharedPersistence"
    ran = [True, True, True, False]
    detections = tuple(
        det(e.release.release_id, {(None, count): 1.0 if r else None}, run=[SP] if r else [])
        for e, r in zip(tl.entries, ran, strict=True)
    )

    with capture_logs() as logs:
        [series] = build(tl, detections)

    assert [p.ordinal for p in series.points] == [0, 1, 2]
    assert reasons(logs) == []  # nothing that was measured is dropped


def test_count_series_of_a_detector_that_never_ran_is_not_built() -> None:
    tl = four_releases()

    series = build(tl, dets(tl, *[{(None, "ap_count.SharedPersistence"): None}] * 4))

    assert series == ()


def test_involvement_share_breaks_where_the_set_of_detectors_changes() -> None:
    tl = four_releases()
    share = "ap_involvement_share"
    detections = (
        det("v1.0.0", {(None, share): 0.2}, run=[CYC]),
        det("v1.1.0", {(None, share): 0.2}, run=[CYC, SP]),
        det("v1.2.0", {(None, share): 0.3}, run=[CYC, SP]),
        det("v1.3.0", {(None, share): 0.4}, run=[SP, CYC]),  # same set, other order
    )

    with capture_logs() as logs:
        [series] = build(tl, detections)

    assert [p.ordinal for p in series.points] == [1, 2, 3]
    assert reasons(logs) == [SERIES_DETECTOR_GAP]


def test_graph_metric_is_not_broken_by_a_detector_that_did_not_run() -> None:
    tl = four_releases()
    detections = tuple(
        det(e.release.release_id, {(None, "modularity"): 0.4}, run=[] if k == 1 else [SP])
        for k, e in enumerate(tl.entries)
    )

    [series] = build(tl, detections)

    assert [p.ordinal for p in series.points] == [0, 1, 2, 3]


# --- the table as a whole -----------------------------------------------------------------------


def mixed() -> tuple[Timeline, tuple[ReleaseDetection, ...]]:
    tl = timeline(rel("v1.0.0", ["b", "a"]), rel("v1.1.0", ["a", "b"]))
    values: Values = {
        (None, "modularity"): 0.4,
        ("b", "size"): 1.0,
        ("a", "size"): 2.0,
        ("a", "fan_in"): 1.0,
        (None, "ap_count.CyclicDependency"): 1.0,
    }
    cycle = [instance(CYC, "a", "b")]
    return tl, dets(tl, values, values, run=[CYC], instances=cycle)


def test_series_are_sorted_by_scope_then_subject_then_metric() -> None:
    series = build(*mixed())

    assert keys(series) == [
        ("ELEMENT", "LIN-a@v1.0.0", "fan_in"),
        ("ELEMENT", "LIN-a@v1.0.0", "size"),
        ("ELEMENT", "LIN-b@v1.0.0", "size"),
        ("INSTANCE", "AP-CyclicDependency:a@v1.0.0", "member_count"),
        ("SYSTEM", "tiny", "ap_count.CyclicDependency"),
        ("SYSTEM", "tiny", "modularity"),
    ]


def test_result_does_not_depend_on_the_order_of_observations() -> None:
    tl, detections = mixed()
    shuffled = tuple(
        d.model_copy(update={"observations": tuple(reversed(d.observations))}) for d in detections
    )

    assert build(tl, shuffled) == build(tl, detections)


def test_no_observations_and_no_instances_means_no_series() -> None:
    tl = timeline(rel("v1.0.0", ["a"]))

    assert build(tl, (det("v1.0.0", {}),)) == ()


def test_duplicate_observation_is_rejected() -> None:
    tl = timeline(rel("v1.0.0", ["a"]))
    twice = MetricObservation(release_id="v1.0.0", element_id="a", metric="size", value=1.0)
    detection = ReleaseDetection(release_id="v1.0.0", observations=(twice, twice))

    with pytest.raises(ValueError, match="twice"):
        build(tl, (detection,))


def test_observation_of_an_element_not_in_the_release_is_rejected() -> None:
    tl = timeline(rel("v1.0.0", ["a"]))

    with pytest.raises(ValueError, match="ghost"):
        build(tl, (det("v1.0.0", {("ghost", "size"): 1.0}),))


def test_observation_of_another_release_is_rejected() -> None:
    tl = timeline(rel("v1.0.0", ["a"]))
    stray = MetricObservation(release_id="v0.9.0", element_id="a", metric="size", value=1.0)

    with pytest.raises(ValueError, match="v0.9.0"):
        build(tl, (ReleaseDetection(release_id="v1.0.0", observations=(stray,)),))


# --- the stub system ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def stub_result() -> TrackingResult:
    files = StubService().generate().system_files
    service = IngestService(InMemoryReleaseRepository(), FixedClock(), CFG)
    service.ingest(
        RawPackage(source=name, data=text.encode("utf-8"))
        for name, text in sorted(files.items())
        if name.endswith(".json")
    )
    tl = service.timeline("shopfront")
    detection = DetectionService(CFG)
    return TrackingService(CFG).track(tl, [detection.detect(e.release) for e in tl.entries])


def test_stub_element_and_system_series_have_the_manifest_lengths(
    stub_result: TrackingResult,
) -> None:
    lengths = StubService().generate().ground_truth.series_lengths
    element = [s for s in stub_result.series if s.scope is Scope.ELEMENT]
    system = [s for s in stub_result.series if s.scope is Scope.SYSTEM]
    element_metrics = {s.metric for s in element}

    assert len(element) == len(stub_result.lineages) * len(element_metrics)
    assert {len(s.points) for s in element} == {lengths.element}
    assert {len(s.points) for s in system} == {lengths.system}
    assert {"modularity", "largest_scc_share", "ap_count.SharedPersistence"} <= {
        s.metric for s in system
    }


def test_stub_instance_series_are_the_planted_instances(stub_result: TrackingResult) -> None:
    truth = StubService().generate().ground_truth

    lengths = {s.subject_id: len(s.points) for s in stub_result.series if s.scope is Scope.INSTANCE}

    # S1 and S9 are the only INSTANCE-scope tracks of the stub: one track each.
    assert sorted(lengths.values()) == sorted(truth.series_lengths.instance.values())
    assert set(lengths) == {
        "AP-CyclicDependency:inventory@v1.1.0",
        "AP-SharedPersistence:orders_db@v1.2.0",
    }


def stub_subject(result: TrackingResult, scope: Scope, subject: str) -> str:
    """Series subject of a manifest subject (last-release element id, scenario id or system)."""
    truth = StubService().generate().ground_truth
    last = truth.releases[-1].release_id
    if scope is Scope.ELEMENT:
        [lineage] = [
            lin.lineage_id
            for lin in result.lineages
            if lin.members[-1].release_id == last and lin.members[-1].element_id == subject
        ]
        return lineage
    if scope is Scope.INSTANCE:
        [planted] = [i for i in truth.instances if i.scenario == subject]
        [track] = [
            t.track_id
            for t in result.tracks
            if t.anti_pattern_type == planted.anti_pattern_type
            and set(t.occurrences[-1].members) == set(planted.members_by_release[last])
        ]
        return track
    return truth.system_id


def test_stub_every_trend_the_manifest_names_has_a_full_series(
    stub_result: TrackingResult,
) -> None:
    truth = StubService().generate().ground_truth
    full = {
        Scope.ELEMENT: truth.series_lengths.element,
        Scope.SYSTEM: truth.series_lengths.system,
    }

    for named in (*truth.expected_trends, *truth.expected_flat):
        subject = stub_subject(stub_result, named.scope, named.subject)
        series = one(stub_result.series, named.scope, subject, named.metric)
        expected = full.get(named.scope) or truth.series_lengths.instance[named.subject]
        assert len(series.points) == expected, (named.scenario, named.metric)
        assert all(p.value is not None for p in series.points), (named.scenario, named.metric)
