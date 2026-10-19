"""M4 candidate assembly: which significant worsening trends become which event candidates."""

from collections.abc import Sequence
from typing import Any

import pytest
from structlog.testing import capture_logs

from app.components.degradation_detection.config import C3Config
from app.components.degradation_detection.detection import DetectionService
from app.components.degradation_detection.models import (
    AntiPatternInstance,
    DetectionCatalog,
    EventCandidate,
    SeriesPoint,
    Timeline,
    TrendResult,
)
from app.components.degradation_detection.tracking import TrackingService
from app.components.degradation_detection.tracking.models import TrackingResult
from app.components.degradation_detection.trends.candidates import (
    METRIC_DRIFT,
    assemble_candidates,
)
from app.components.degradation_detection.trends.models import (
    CANDIDATE_INSTANCE_AMBIGUOUS,
    TREND_ON_ENDED_INSTANCE,
)
from app.domain.canonical_release import GateStatus
from app.domain.degradation_event import Lifecycle, Scope, TestMethod, TimeAxis, Worsening
from app.shared.canonical_json import content_hash
from tests.components.degradation_detection.tracking.timelines import (
    detections,
    el,
    instance,
    rel,
    timeline,
)

CFG = C3Config()
CATALOG = DetectionService(CFG).describe()
N = 8  # releases v1.0.0 .. v1.7.0
LAST = N - 1
SYSTEM = "tiny"

CYC = "CyclicDependency"
HUB = "HubLikeElement"
BBOM = "BigBallOfMud"
SHARED = "SharedPersistence"
UNSTABLE = "UnstableDependency"

RAN = (CYC, HUB, UNSTABLE, "OversizedElement", BBOM, SHARED)


def cycle(*members: str) -> AntiPatternInstance:
    return instance(CYC, *members)


def hub(element: str) -> AntiPatternInstance:
    return instance(HUB, element, scope=Scope.ELEMENT)


def mud(*members: str) -> AntiPatternInstance:
    return instance(BBOM, *members, scope=Scope.SYSTEM, key="system")


def build(
    per_release: Sequence[Sequence[AntiPatternInstance]],
    *,
    downweighted: Sequence[int] = (),
    renamed_at: int | None = None,
) -> tuple[Timeline, TrackingResult]:
    """Elements a, b, c, d in every release (d becomes d2 at ``renamed_at``)."""
    releases = []
    for k in range(len(per_release)):
        d = el("d2", aliases=["d"]) if renamed_at is not None and k >= renamed_at else "d"
        r = rel(f"v1.{k}.0", ["a", "b", "c", d])
        if k in downweighted:
            r = r.model_copy(update={"gate_status": GateStatus.DOWNWEIGHTED})
        releases.append(r)
    tl = timeline(*releases)
    return tl, TrackingService(CFG).track(tl, detections(tl, *per_release, run=RAN))


def every(*found: AntiPatternInstance, n: int = N) -> list[list[AntiPatternInstance]]:
    return [list(found) for _ in range(n)]


def trend(
    scope: Scope,
    subject: str,
    metric: str,
    *,
    significant: bool = True,
    worsening: bool = True,
    tau: float = 0.8,
    first: int = 0,
    last: int = LAST,
    direction: Worsening = Worsening.INCREASE,
    nulls: Sequence[int] = (),
) -> TrendResult:
    points = tuple(
        SeriesPoint(ordinal=k, release_id=f"v1.{k}.0", value=None if k in nulls else float(k))
        for k in range(first, last + 1)
    )
    return TrendResult(
        scope=scope,
        subject_id=subject,
        metric=metric,
        unit="count",
        worsening=direction,
        points=points,
        n=sum(1 for p in points if p.value is not None),
        s=20,
        tau=tau,
        p_value=0.001,
        q_value=0.01 if significant else 0.2,
        method=TestMethod.EXACT,
        time_axis=TimeAxis.ORDINAL,
        sen_slope=1.0,
        intercept=0.0,
        is_worsening=worsening,
        is_significant=significant,
    )


def element(subject: str, metric: str, **kw: Any) -> TrendResult:
    return trend(Scope.ELEMENT, subject, metric, **kw)


def system(metric: str, **kw: Any) -> TrendResult:
    return trend(Scope.SYSTEM, SYSTEM, metric, **kw)


def assemble(
    tl: Timeline,
    tracked: TrackingResult,
    *results: TrendResult,
    catalog: DetectionCatalog = CATALOG,
) -> tuple[EventCandidate, ...]:
    return assemble_candidates(results, tl, tracked.lineages, tracked.tracks, catalog)


def summary(candidates: Sequence[EventCandidate]) -> list[tuple[str, str, str, list[str]]]:
    """(scope, subject, type, metrics) per candidate."""
    return [
        (c.scope.value, c.subject_id, c.anti_pattern_type, [t.metric for t in c.trends])
        for c in candidates
    ]


LIN_A = "LIN-a@v1.0.0"
LIN_C = "LIN-c@v1.0.0"
CYCLE_TRACK = "AP-CyclicDependency:a@v1.0.0"
HUB_TRACK = "AP-HubLikeElement:c@v1.0.0"
MUD_TRACK = "AP-BigBallOfMud:system@v1.0.0"


# --- only significant and worsening trends count -----------------------------------------


@pytest.mark.parametrize(
    ("significant", "worsening", "expected"),
    [(True, True, 1), (True, False, 0), (False, True, 0), (False, False, 0)],
    ids=["significant-worsening", "significant-improving", "not-significant", "neither"],
)
@pytest.mark.parametrize(
    ("scope", "subject", "metric"),
    [
        (Scope.INSTANCE, CYCLE_TRACK, "member_count"),
        (Scope.ELEMENT, LIN_C, "fan_in_norm"),
        (Scope.SYSTEM, SYSTEM, "largest_scc_share"),
    ],
    ids=["instance", "element", "system"],
)
def test_a_candidate_needs_a_significant_worsening_trend(
    scope: Scope, subject: str, metric: str, significant: bool, worsening: bool, expected: int
) -> None:
    tl, tracked = build(every(cycle("a", "b"), hub("c"), mud("a", "b")))
    result = trend(scope, subject, metric, significant=significant, worsening=worsening)

    assert len(assemble(tl, tracked, result)) == expected


def test_no_results_give_no_candidates() -> None:
    tl, tracked = build(every())

    assert assemble(tl, tracked) == ()


# --- INSTANCE -----------------------------------------------------------------------------


def test_worsening_instance_measure_of_an_open_track_is_a_growing_instance_candidate() -> None:
    tl, tracked = build(every(cycle("a", "b")))

    [c] = assemble(tl, tracked, trend(Scope.INSTANCE, CYCLE_TRACK, "member_count"))

    assert (c.scope, c.subject_id, c.anti_pattern_type, c.catalog) == (
        Scope.INSTANCE,
        CYCLE_TRACK,
        CYC,
        "universal",
    )
    assert (c.instance_id, c.members, c.lifecycle) == (CYCLE_TRACK, ("a", "b"), Lifecycle.GROWING)
    assert (c.element_id, c.lineage_id) == (None, None)


def test_members_are_the_ones_in_the_last_release() -> None:
    tl, tracked = build([[cycle("a", "b")]] * 4 + [[cycle("a", "b", "c")]] * 4)

    [c] = assemble(tl, tracked, trend(Scope.INSTANCE, CYCLE_TRACK, "member_count"))

    assert c.members == ("a", "b", "c")


def test_instance_gone_from_the_last_release_is_not_a_candidate() -> None:
    tl, tracked = build([[cycle("a", "b")]] * N + [[]])

    with capture_logs() as logs:
        candidates = assemble(tl, tracked, trend(Scope.INSTANCE, CYCLE_TRACK, "member_count"))

    assert candidates == ()
    assert TREND_ON_ENDED_INSTANCE in [e.get("reason") for e in logs]


def test_two_worsening_measures_of_one_instance_are_one_candidate() -> None:
    tl, tracked = build(every(cycle("a", "b")))

    [c] = assemble(
        tl,
        tracked,
        trend(Scope.INSTANCE, CYCLE_TRACK, "member_count", tau=0.7),
        trend(Scope.INSTANCE, CYCLE_TRACK, "internal_edge_count", tau=0.9),
    )

    assert [t.metric for t in c.trends] == ["internal_edge_count", "member_count"]
    assert c.trend_strength == 0.9


# --- ELEMENT ------------------------------------------------------------------------------


def test_driving_metric_of_an_anti_pattern_present_on_the_element_gives_that_type() -> None:
    tl, tracked = build(every(hub("c")))

    [c] = assemble(tl, tracked, element(LIN_C, "fan_in_norm"), element(LIN_C, "fan_out_norm"))

    assert (c.scope, c.subject_id, c.anti_pattern_type) == (Scope.ELEMENT, LIN_C, HUB)
    assert (c.element_id, c.lineage_id) == ("c", LIN_C)
    assert (c.instance_id, c.members, c.lifecycle) == (HUB_TRACK, ("c",), Lifecycle.GROWING)
    assert [t.metric for t in c.trends] == ["fan_in_norm", "fan_out_norm"]


def test_member_of_an_instance_anti_pattern_gets_an_element_candidate_of_that_type() -> None:
    tl, tracked = build(every(cycle("a", "b")))

    [c] = assemble(tl, tracked, element(LIN_A, "scc_size"))

    assert (c.scope, c.anti_pattern_type, c.element_id) == (Scope.ELEMENT, CYC, "a")
    assert (c.instance_id, c.members) == (CYCLE_TRACK, ("a", "b"))


def test_newly_present_anti_pattern_keeps_its_introduced_lifecycle() -> None:
    tl, tracked = build([[]] * LAST + [[hub("c")]])

    [c] = assemble(tl, tracked, element(LIN_C, "fan_in_norm"))

    assert c.anti_pattern_type == HUB
    assert c.lifecycle is Lifecycle.INTRODUCED


def test_worsening_metric_that_drives_nothing_present_is_metric_drift() -> None:
    tl, tracked = build(every(hub("c")))

    [c] = assemble(tl, tracked, element(LIN_A, "fan_in_norm"))  # a is not a hub

    assert (c.scope, c.anti_pattern_type, c.catalog) == (Scope.ELEMENT, METRIC_DRIFT, "universal")
    assert (c.element_id, c.lineage_id) == ("a", LIN_A)
    assert (c.instance_id, c.members, c.lifecycle) == (None, (), None)


def test_anti_pattern_must_be_present_in_the_last_release_of_the_window() -> None:
    tl, tracked = build([[hub("c")]] * LAST + [[]])

    [c] = assemble(tl, tracked, element(LIN_C, "fan_in_norm"))

    assert c.anti_pattern_type == METRIC_DRIFT


def test_uncovered_trends_of_one_element_are_one_metric_drift_beside_its_anti_pattern() -> None:
    tl, tracked = build(every(hub("c")))

    candidates = assemble(
        tl,
        tracked,
        element(LIN_C, "fan_in_norm"),
        element(LIN_C, "fan_in"),
        element(LIN_C, "size"),
    )

    assert summary(candidates) == [
        ("ELEMENT", LIN_C, HUB, ["fan_in_norm"]),
        ("ELEMENT", LIN_C, METRIC_DRIFT, ["fan_in", "size"]),
    ]


def test_element_id_is_the_one_in_the_last_release_of_the_window() -> None:
    tl, tracked = build(every(), renamed_at=4)

    [c] = assemble(tl, tracked, element("LIN-d@v1.0.0", "size"))

    assert (c.lineage_id, c.element_id) == ("LIN-d@v1.0.0", "d2")


def test_two_instances_of_one_type_on_an_element_name_no_instance() -> None:
    """Not reachable with the built-in catalog; when it is, do not pick one of them."""
    shared = CATALOG.detector(SHARED).model_copy(update={"driving_metrics": ("fan_in",)})
    catalog = CATALOG.model_copy(
        update={
            "detectors": tuple(
                shared if d.anti_pattern_type == SHARED else d for d in CATALOG.detectors
            )
        }
    )
    stores = [instance(SHARED, "a", "b", key="db1"), instance(SHARED, "a", "c", key="db2")]
    tl, tracked = build([stores] * N)

    with capture_logs() as logs:
        [c] = assemble(tl, tracked, element(LIN_A, "fan_in"), catalog=catalog)

    assert (c.anti_pattern_type, c.instance_id, c.members, c.lifecycle) == (
        SHARED,
        None,
        (),
        None,
    )
    assert CANDIDATE_INSTANCE_AMBIGUOUS in [e.get("reason") for e in logs]


# --- SYSTEM -------------------------------------------------------------------------------


def test_anti_pattern_count_gives_the_counted_type() -> None:
    tl, tracked = build(every())

    [c] = assemble(tl, tracked, system("ap_count.UnstableDependency"))

    assert (c.scope, c.subject_id, c.anti_pattern_type, c.catalog) == (
        Scope.SYSTEM,
        SYSTEM,
        UNSTABLE,
        "universal",
    )
    assert (c.instance_id, c.members, c.lifecycle) == (None, (), None)


def test_driving_metric_of_a_present_system_anti_pattern_gives_that_type() -> None:
    tl, tracked = build(every(mud("a", "b")))

    [c] = assemble(
        tl,
        tracked,
        system("largest_scc_share", tau=0.8),
        system("modularity", tau=-0.9, direction=Worsening.DECREASE),
    )

    assert (c.anti_pattern_type, c.instance_id, c.members) == (BBOM, MUD_TRACK, ("a", "b"))
    assert c.lifecycle is Lifecycle.GROWING
    assert c.trend_strength == 0.9  # |tau|: evidence strength, the sign is the direction


def test_system_driving_metric_without_the_anti_pattern_present_is_metric_drift() -> None:
    tl, tracked = build([[mud("a", "b")]] * LAST + [[]])

    [c] = assemble(tl, tracked, system("largest_scc_share"))

    assert (c.anti_pattern_type, c.instance_id) == (METRIC_DRIFT, None)


def test_other_system_trends_are_one_metric_drift() -> None:
    tl, tracked = build(every(mud("a", "b")))

    candidates = assemble(
        tl,
        tracked,
        system("cyclic_edge_count"),
        system("ap_involvement_share"),
        system("largest_scc_share"),
        system("ap_count.BigBallOfMud"),
    )

    assert summary(candidates) == [
        ("SYSTEM", SYSTEM, BBOM, ["ap_count.BigBallOfMud", "largest_scc_share"]),
        ("SYSTEM", SYSTEM, METRIC_DRIFT, ["ap_involvement_share", "cyclic_edge_count"]),
    ]


# --- every candidate: window, low confidence, key, order ---------------------------------


def test_window_is_the_span_of_the_tested_points() -> None:
    tl, tracked = build(every(), downweighted=(0, 3))

    [c] = assemble(
        tl,
        tracked,
        system("cyclic_edge_count", first=1, last=LAST, nulls=(1,)),
        system("ap_involvement_share", first=2, last=6),
    )

    assert (c.start_release, c.end_release, c.n_releases) == ("v1.2.0", "v1.7.0", 6)
    assert c.low_confidence_releases == ("v1.3.0",)  # v1.0.0 is outside the window


def test_event_key_is_the_plan_hash_and_ignores_the_end_release() -> None:
    tl, tracked = build(every(hub("c")))
    longer_tl, longer = build(every(hub("c"), n=N + 2))

    [c] = assemble(tl, tracked, element(LIN_C, "fan_in_norm"))
    [later] = assemble(longer_tl, longer, element(LIN_C, "fan_in_norm", last=N + 1))

    assert c.event_key == content_hash(
        {
            "system_id": SYSTEM,
            "scope": "ELEMENT",
            "subject_id": LIN_C,
            "anti_pattern_type": HUB,
            "catalog": "universal",
            "start_release": "v1.0.0",
        }
    )
    assert later.end_release != c.end_release
    assert later.event_key == c.event_key


def test_event_keys_differ_by_type_on_one_subject() -> None:
    tl, tracked = build(every(hub("c")))

    hub_candidate, drift = assemble(
        tl, tracked, element(LIN_C, "fan_in_norm"), element(LIN_C, "size")
    )

    assert hub_candidate.event_key != drift.event_key


def test_candidates_are_sorted_by_scope_subject_and_type_whatever_the_input_order() -> None:
    tl, tracked = build(every(cycle("a", "b"), hub("c"), mud("a", "b")))
    results = [
        system("cyclic_edge_count"),
        system("largest_scc_share"),
        trend(Scope.INSTANCE, CYCLE_TRACK, "member_count"),
        element(LIN_C, "size"),
        element(LIN_C, "fan_in_norm"),
        element(LIN_A, "scc_size"),
    ]

    forward = assemble(tl, tracked, *results)
    backward = assemble(tl, tracked, *reversed(results))

    assert forward == backward
    assert [(c.scope.value, c.subject_id, c.anti_pattern_type) for c in forward] == [
        ("ELEMENT", LIN_A, CYC),
        ("ELEMENT", LIN_C, HUB),
        ("ELEMENT", LIN_C, METRIC_DRIFT),
        ("INSTANCE", CYCLE_TRACK, CYC),
        ("SYSTEM", SYSTEM, BBOM),
        ("SYSTEM", SYSTEM, METRIC_DRIFT),
    ]


def test_trend_on_an_unknown_subject_is_an_error() -> None:
    tl, tracked = build(every())

    with pytest.raises(KeyError, match="LIN-zz"):
        assemble(tl, tracked, element("LIN-zz@v1.0.0", "size"))
    with pytest.raises(KeyError, match="AP-zz"):
        assemble(tl, tracked, trend(Scope.INSTANCE, "AP-zz", "member_count"))
