"""M3 instance tracking and lifecycle through ``TrackingService.track`` (T-09)."""

from collections.abc import Sequence

import pytest
from structlog.testing import capture_logs

from app.components.degradation_detection.config import C3Config, TrackingConfig
from app.components.degradation_detection.detection import DetectionService
from app.components.degradation_detection.ingestion import IngestService
from app.components.degradation_detection.ingestion.models import RawPackage
from app.components.degradation_detection.models import (
    AntiPatternInstance,
    InstanceTrack,
    InstanceTransition,
    ReleaseDetection,
    Timeline,
    TrackEnd,
)
from app.components.degradation_detection.stub import StubService
from app.components.degradation_detection.tracking import TrackingService
from app.components.degradation_detection.tracking.models import (
    INSTANCE_MATCH_AMBIGUOUS,
    INSTANCE_TRACK_UNCHECKED,
)
from app.domain.degradation_event import Lifecycle, Scope
from tests.components.degradation_detection.fakes import FixedClock, InMemoryReleaseRepository
from tests.components.degradation_detection.tracking.timelines import (
    detections,
    el,
    instance,
    rel,
    timeline,
)

CFG = C3Config()
CYC = "CyclicDependency"
HUB = "HubLikeElement"
OVERSIZED = "OversizedElement"
BBOM = "BigBallOfMud"
RUN = (CYC, HUB, OVERSIZED, BBOM)
ELEMENTS = ["a", "b", "c", "d", "e", "f"]


def tracks(
    tl: Timeline, found: Sequence[ReleaseDetection], cfg: C3Config = CFG
) -> tuple[InstanceTrack, ...]:
    return TrackingService(cfg).track(tl, found).tracks


def same_elements(n: int) -> Timeline:
    """``n`` releases v1.0.0, v1.1.0, ... with the same elements."""
    return timeline(*(rel(f"v1.{k}.0", ELEMENTS) for k in range(n)))


def cyc(*members: str) -> list[AntiPatternInstance]:
    return [instance(CYC, *members)]


def summary(track: InstanceTrack) -> list[tuple[str, tuple[str, ...]]]:
    """[(release_id, members), ...] of a track."""
    return [(o.release_id, o.members) for o in track.occurrences]


def reasons(logs: list[dict[str, object]]) -> list[object]:
    return [entry.get("reason") for entry in logs if "reason" in entry]


# --- one track per instance -------------------------------------------------------------------


def test_instance_present_in_every_release_is_one_open_persistent_track() -> None:
    tl = same_elements(3)

    [track] = tracks(tl, detections(tl, cyc("a", "b"), cyc("a", "b"), cyc("a", "b"), run=RUN))

    assert track.track_id == "AP-CyclicDependency:a@v1.0.0"
    assert (track.anti_pattern_type, track.catalog, track.scope) == (
        CYC,
        "universal",
        Scope.INSTANCE,
    )
    assert summary(track) == [(f"v1.{k}.0", ("a", "b")) for k in range(3)]
    assert [o.ordinal for o in track.occurrences] == [0, 1, 2]
    assert [o.transition for o in track.occurrences] == [
        InstanceTransition.INTRODUCED,
        InstanceTransition.PERSISTED,
        InstanceTransition.PERSISTED,
    ]
    assert (track.end, track.ended_at, track.lifecycle) == (
        TrackEnd.OPEN,
        None,
        Lifecycle.PERSISTENT,
    )


def test_occurrence_keeps_the_m2_instance_and_its_member_lineages() -> None:
    tl = same_elements(2)

    [track] = tracks(tl, detections(tl, cyc("a", "b"), cyc("b", "a"), run=RUN))

    first, second = track.occurrences
    assert first.local_instance_id == "CyclicDependency:a"
    assert first.member_lineages == ("LIN-a@v1.0.0", "LIN-b@v1.0.0")
    assert first.measures == {"member_count": 2.0}
    assert (first.jaccard, second.jaccard) == (None, 1.0)


def test_instance_survives_a_member_rename() -> None:
    tl = timeline(
        rel("v1.0.0", ["a", "b", "c"]),
        rel("v1.1.0", ["a", el("b2", aliases=["b"]), "c"]),
    )

    [track] = tracks(tl, detections(tl, cyc("a", "b"), cyc("a", "b2"), run=RUN))

    assert summary(track) == [("v1.0.0", ("a", "b")), ("v1.1.0", ("a", "b2"))]
    assert track.occurrences[1].member_lineages == ("LIN-a@v1.0.0", "LIN-b@v1.0.0")
    assert track.occurrences[1].jaccard == 1.0


def test_member_whose_lineage_breaks_counts_as_a_different_member() -> None:
    # b becomes a library: same id, new kind, so a new lineage. The cycle keeps 2 of 3 members.
    tl = timeline(
        rel("v1.0.0", ["a", "b", "c"]),
        rel("v1.1.0", ["a", el("b", kind="library"), "c"]),
    )

    [track] = tracks(tl, detections(tl, cyc("a", "b", "c"), cyc("a", "b", "c"), run=RUN))

    assert track.occurrences[1].jaccard == pytest.approx(2 / 4)  # {a,b,c} vs {a,b',c}
    assert len(track.occurrences) == 2  # 0.5 still reaches the default minimum


def test_growing_cycle_stays_one_track() -> None:
    tl = same_elements(3)

    [track] = tracks(
        tl, detections(tl, cyc("a", "b", "c"), cyc("a", "b", "c", "d"), cyc(*"abcde"), run=RUN)
    )

    assert [len(o.members) for o in track.occurrences] == [3, 4, 5]
    assert [o.transition for o in track.occurrences] == [
        InstanceTransition.INTRODUCED,
        InstanceTransition.GREW,
        InstanceTransition.GREW,
    ]
    assert [o.jaccard for o in track.occurrences] == [None, 0.75, 0.8]


def test_shrinking_cycle_is_labelled_shrank() -> None:
    tl = same_elements(2)

    [track] = tracks(tl, detections(tl, cyc("a", "b", "c"), cyc("a", "b"), run=RUN))

    assert track.occurrences[1].transition is InstanceTransition.SHRANK


def test_cycle_that_disappears_is_resolved_at_the_next_release() -> None:
    tl = same_elements(4)

    [track] = tracks(tl, detections(tl, cyc("a", "b"), cyc("a", "b"), [], [], run=RUN))

    assert [o.release_id for o in track.occurrences] == ["v1.0.0", "v1.1.0"]
    assert (track.end, track.ended_at, track.lifecycle) == (
        TrackEnd.RESOLVED,
        "v1.2.0",
        Lifecycle.RESOLVED,
    )


def test_instance_first_seen_in_the_last_release_is_introduced() -> None:
    tl = same_elements(3)

    [track] = tracks(tl, detections(tl, [], [], cyc("a", "b"), run=RUN))

    assert track.track_id == "AP-CyclicDependency:a@v1.2.0"
    assert (track.end, track.lifecycle) == (TrackEnd.OPEN, Lifecycle.INTRODUCED)


def test_instance_that_returns_starts_a_new_track() -> None:
    tl = same_elements(3)

    first, second = tracks(tl, detections(tl, cyc("a", "b"), [], cyc("a", "b"), run=RUN))

    assert (first.track_id, first.end, first.ended_at) == (
        "AP-CyclicDependency:a@v1.0.0",
        TrackEnd.RESOLVED,
        "v1.1.0",
    )
    assert (second.track_id, second.lifecycle) == (
        "AP-CyclicDependency:a@v1.2.0",
        Lifecycle.INTRODUCED,
    )


# --- matching ---------------------------------------------------------------------------------


def test_two_unrelated_cycles_never_share_a_track() -> None:
    tl = same_elements(2)
    both = [instance(CYC, "a", "b"), instance(CYC, "c", "d")]

    result = tracks(tl, detections(tl, both, list(reversed(both)), run=RUN))

    assert [summary(t) for t in result] == [
        [("v1.0.0", ("a", "b")), ("v1.1.0", ("a", "b"))],
        [("v1.0.0", ("c", "d")), ("v1.1.0", ("c", "d"))],
    ]


def test_cycle_that_moves_to_other_elements_is_a_new_track() -> None:
    tl = same_elements(2)

    first, second = tracks(tl, detections(tl, cyc("a", "b", "c"), cyc("c", "d", "e"), run=RUN))

    assert (first.end, first.ended_at) == (TrackEnd.RESOLVED, "v1.1.0")  # J = 1/5
    assert second.track_id == "AP-CyclicDependency:c@v1.1.0"


def test_jaccard_minimum_comes_from_config() -> None:
    tl = same_elements(2)
    found = detections(tl, cyc("a", "b"), cyc("a", "b", "c", "d"), run=RUN)  # J = 0.5
    strict = CFG.model_copy(update={"tracking": TrackingConfig(instance_jaccard_min=0.6)})

    assert len(tracks(tl, found)) == 1  # 0.5 reaches the minimum exactly
    assert len(tracks(tl, found, strict)) == 2


def test_two_cycles_merging_into_one_is_a_tie_and_links_neither() -> None:
    tl = same_elements(2)
    found = detections(
        tl, [instance(CYC, "a", "b"), instance(CYC, "c", "d")], cyc("a", "b", "c", "d"), run=RUN
    )

    with capture_logs() as logs:
        result = tracks(tl, found)

    assert [(t.track_id, t.end) for t in result] == [
        ("AP-CyclicDependency:a@v1.0.0", TrackEnd.RESOLVED),
        ("AP-CyclicDependency:c@v1.0.0", TrackEnd.RESOLVED),
        ("AP-CyclicDependency:a@v1.1.0", TrackEnd.OPEN),
    ]
    assert INSTANCE_MATCH_AMBIGUOUS in reasons(logs)


def test_cycle_splitting_into_two_equal_halves_is_a_tie_and_links_neither() -> None:
    tl = same_elements(2)
    found = detections(
        tl, cyc("a", "b", "c", "d"), [instance(CYC, "a", "b"), instance(CYC, "c", "d")], run=RUN
    )

    result = tracks(tl, found)

    assert [len(t.occurrences) for t in result] == [1, 1, 1]


def test_types_are_tracked_separately() -> None:
    tl = same_elements(2)
    found = detections(tl, [instance(HUB, "a")], [instance(OVERSIZED, "a")], run=RUN)

    hub, oversized = tracks(tl, found)

    assert (hub.anti_pattern_type, hub.end) == (HUB, TrackEnd.RESOLVED)
    assert (oversized.anti_pattern_type, oversized.lifecycle) == (OVERSIZED, Lifecycle.INTRODUCED)


def test_element_scope_instance_follows_the_lineage_of_its_element() -> None:
    tl = timeline(
        rel("v1.0.0", ["a", "b"]),
        rel("v1.1.0", [el("a2", aliases=["a"]), "b"]),
        rel("v1.2.0", ["a2", "b"]),
    )
    hub = [instance(HUB, "a", scope=Scope.ELEMENT)]
    hub2 = [instance(HUB, "a2", scope=Scope.ELEMENT)]

    hub_b = [instance(HUB, "b", scope=Scope.ELEMENT)]

    first, second = tracks(tl, detections(tl, hub, hub2, hub_b, run=RUN))

    assert summary(first) == [("v1.0.0", ("a",)), ("v1.1.0", ("a2",))]
    assert (first.end, first.ended_at) == (TrackEnd.RESOLVED, "v1.2.0")
    assert second.track_id == "AP-HubLikeElement:b@v1.2.0"


def test_big_ball_of_mud_is_one_track_while_present_whatever_its_members() -> None:
    tl = same_elements(4)

    def mud(*members: str) -> list[AntiPatternInstance]:
        return [instance(BBOM, *members, scope=Scope.SYSTEM, key="system")]

    [track] = tracks(tl, detections(tl, mud("a", "b"), mud("c", "d"), mud("e", "f"), [], run=RUN))

    assert track.track_id == "AP-BigBallOfMud:system@v1.0.0"
    assert [o.jaccard for o in track.occurrences] == [None, 0.0, 0.0]
    assert (track.end, track.ended_at) == (TrackEnd.RESOLVED, "v1.3.0")


# --- a type that was not checked --------------------------------------------------------------


def test_release_that_did_not_run_the_detector_ends_the_track_without_resolving_it() -> None:
    tl = same_elements(3)
    found = detections(tl, cyc("a", "b"), [], cyc("a", "b"), run=RUN, not_run={1: [CYC]})

    with capture_logs() as logs:
        first, second = tracks(tl, found)

    assert (first.end, first.ended_at, first.lifecycle) == (TrackEnd.UNCHECKED, "v1.1.0", None)
    assert (second.track_id, second.lifecycle) == (
        "AP-CyclicDependency:a@v1.2.0",
        Lifecycle.INTRODUCED,
    )
    assert INSTANCE_TRACK_UNCHECKED in reasons(logs)


def test_track_is_not_resolved_when_the_detector_did_not_run_in_the_last_release() -> None:
    tl = same_elements(2)
    found = detections(tl, cyc("a", "b"), [], run=RUN, not_run={1: [CYC]})

    [track] = tracks(tl, found)

    assert (track.end, track.ended_at, track.lifecycle) == (TrackEnd.UNCHECKED, "v1.1.0", None)


def test_other_types_are_unaffected_by_a_detector_that_did_not_run() -> None:
    tl = same_elements(2)
    found = detections(
        tl,
        [instance(CYC, "a", "b"), instance(HUB, "c")],
        [instance(HUB, "c")],
        run=RUN,
        not_run={1: [CYC]},
    )

    cycle, hub = tracks(tl, found)

    assert cycle.end is TrackEnd.UNCHECKED
    assert (hub.end, len(hub.occurrences)) == (TrackEnd.OPEN, 2)


# --- invariants and determinism ---------------------------------------------------------------


def test_result_does_not_depend_on_the_order_of_instances() -> None:
    tl = same_elements(2)
    first = [instance(CYC, "a", "b"), instance(CYC, "c", "d"), instance(HUB, "e")]
    second = [instance(HUB, "e"), instance(CYC, "c", "d", "f"), instance(CYC, "a", "b")]

    forward = tracks(tl, detections(tl, first, second, run=RUN))
    backward = tracks(
        tl, detections(tl, list(reversed(first)), list(reversed(second)), run=RUN[::-1])
    )

    assert forward == backward


def test_no_detections_means_no_tracks() -> None:
    tl = same_elements(2)

    assert tracks(tl, detections(tl, [], [], run=())) == ()


def test_detections_must_line_up_with_the_timeline() -> None:
    tl = same_elements(2)
    found = detections(tl, [], [], run=RUN)

    with pytest.raises(ValueError, match="one detection per release"):
        tracks(tl, found[:1])
    with pytest.raises(ValueError, match="v1.1.0"):
        tracks(tl, tuple(reversed(found)))


def test_instance_of_a_detector_that_did_not_run_is_rejected() -> None:
    tl = same_elements(1)

    with pytest.raises(ValueError, match="did not run"):
        tracks(tl, detections(tl, cyc("a", "b"), run=(HUB,)))


def test_member_that_is_not_an_element_of_the_release_is_rejected() -> None:
    tl = same_elements(1)

    with pytest.raises(ValueError, match="zz"):
        tracks(tl, detections(tl, cyc("a", "zz"), run=RUN))


def test_system_scope_type_with_two_instances_in_a_release_is_rejected() -> None:
    tl = same_elements(2)
    one = instance(BBOM, "a", "b", scope=Scope.SYSTEM, key="system")
    two = [one, instance(BBOM, "c", "d", scope=Scope.SYSTEM, key="other")]

    with pytest.raises(ValueError, match="system-scope"):
        tracks(tl, detections(tl, [one], two, run=RUN))


# --- the stub system --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def stub_run() -> tuple[Timeline, tuple[ReleaseDetection, ...]]:
    files = StubService().generate().system_files
    service = IngestService(InMemoryReleaseRepository(), FixedClock(), CFG)
    service.ingest(
        RawPackage(source=name, data=text.encode("utf-8"))
        for name, text in sorted(files.items())
        if name.endswith(".json")
    )
    tl = service.timeline("shopfront")
    detection = DetectionService(CFG)
    return tl, tuple(detection.detect(entry.release) for entry in tl.entries)


@pytest.mark.parametrize("scenario", ["S1", "S9"])
def test_stub_planted_instance_is_one_track(
    stub_run: tuple[Timeline, tuple[ReleaseDetection, ...]], scenario: str
) -> None:
    truth = StubService().generate().ground_truth
    [planted] = [i for i in truth.instances if i.scenario == scenario]

    result = tracks(*stub_run)

    [track] = [
        t
        for t in result
        if t.anti_pattern_type == planted.anti_pattern_type
        and t.occurrences[0].release_id == planted.first_release
        and set(t.occurrences[0].members) == set(planted.members_by_release[planted.first_release])
    ]
    assert {o.release_id: set(o.members) for o in track.occurrences} == {
        release: set(members) for release, members in planted.members_by_release.items()
    }
    assert len(track.occurrences) == truth.series_lengths.instance[scenario]
    assert (track.end, track.lifecycle) == (TrackEnd.OPEN, Lifecycle.PERSISTENT)


def test_stub_s1_cycle_keeps_its_track_through_the_s4_rename(
    stub_run: tuple[Timeline, tuple[ReleaseDetection, ...]],
) -> None:
    truth = StubService().generate().ground_truth
    [rename] = truth.renames

    [cycle] = [t for t in tracks(*stub_run) if t.anti_pattern_type == CYC]

    renamed_at = [o.release_id for o in cycle.occurrences].index(rename.at_release)
    before, after = cycle.occurrences[renamed_at - 1], cycle.occurrences[renamed_at]
    assert rename.from_id in before.members and rename.to_id in after.members
    assert f"LIN-{rename.from_id}@v1.0.0" in after.member_lineages
    # The renamed member counts as the same one (shipping also joins the cycle in this release).
    old = {rename.to_id if m == rename.from_id else m for m in before.members}
    new = set(after.members)
    assert after.jaccard == pytest.approx(len(old & new) / len(old | new))
