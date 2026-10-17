"""M3 element alignment and lineages through ``TrackingService.track`` (T-08)."""

import pytest
from structlog.testing import capture_logs

from app.components.degradation_detection.config import AlignConfig, AlignWeights, C3Config
from app.components.degradation_detection.ingestion import IngestService
from app.components.degradation_detection.ingestion.models import RawPackage
from app.components.degradation_detection.models import (
    AlignMethod,
    Lineage,
    LineageEventType,
    Timeline,
)
from app.components.degradation_detection.stub import StubService
from app.components.degradation_detection.tracking import TrackingService
from app.components.degradation_detection.tracking.models import (
    ALIAS_CONFLICT,
    ALIGNMENT_AMBIGUOUS,
    LINEAGE_KIND_CHANGED,
    AlignOutcome,
    TrackingResult,
)
from tests.components.degradation_detection.fakes import FixedClock, InMemoryReleaseRepository
from tests.components.degradation_detection.tracking.timelines import el, rel, timeline

CFG = C3Config()


def track(tl: Timeline, cfg: C3Config = CFG) -> TrackingResult:
    return TrackingService(cfg).track(tl)


def chains(result: TrackingResult) -> dict[str, list[tuple[str, str]]]:
    """lineage id -> [(release_id, element_id), ...]."""
    return {
        lin.lineage_id: [(m.release_id, m.element_id) for m in lin.members]
        for lin in result.lineages
    }


def lineage_of(result: TrackingResult, element_id: str, release_id: str) -> Lineage:
    [found] = [
        lin
        for lin in result.lineages
        if any(m.element_id == element_id and m.release_id == release_id for m in lin.members)
    ]
    return found


def reasons(logs: list[dict[str, object]]) -> list[object]:
    return [entry.get("reason") for entry in logs if "reason" in entry]


# The order service is renamed with nothing but similarity to go on: same neighbours, same size.
SIMILARITY_RENAME = timeline(
    rel("v1.0.0", ["a", "b", "c", "order-svc"], [("a", "order-svc"), ("order-svc", "b")]),
    rel(
        "v1.1.0", ["a", "b", "c", "order-service"], [("a", "order-service"), ("order-service", "b")]
    ),
)


# --- exact pass -------------------------------------------------------------------------------


def test_same_id_continues_its_lineage() -> None:
    result = track(timeline(rel("v1.0.0", ["a", "b"]), rel("v1.1.0", ["a", "b"])))

    assert chains(result) == {
        "LIN-a@v1.0.0": [("v1.0.0", "a"), ("v1.1.0", "a")],
        "LIN-b@v1.0.0": [("v1.0.0", "b"), ("v1.1.0", "b")],
    }
    assert result.events == ()
    assert result.decisions == ()  # exact matches are not decisions to check


def test_lineage_members_carry_the_timeline_ordinal() -> None:
    result = track(timeline(rel("v1.0.0", ["a"]), rel("v1.1.0", ["a"]), rel("v1.2.0", ["a"])))

    assert [m.ordinal for m in result.lineages[0].members] == [0, 1, 2]


def test_empty_timeline_has_no_lineages() -> None:
    result = track(Timeline(system_id="tiny", entries=()))

    assert (result.system_id, result.lineages, result.events) == ("tiny", (), ())


def test_element_missing_from_a_release_starts_a_new_lineage_when_it_returns() -> None:
    result = track(
        timeline(rel("v1.0.0", ["a", "x"]), rel("v1.1.0", ["a"]), rel("v1.2.0", ["a", "x"]))
    )

    assert chains(result)["LIN-x@v1.0.0"] == [("v1.0.0", "x")]
    assert chains(result)["LIN-x@v1.2.0"] == [("v1.2.0", "x")]


def test_kind_change_breaks_the_lineage() -> None:
    with capture_logs() as logs:
        result = track(
            timeline(
                rel("v1.0.0", [el("a", kind="service"), "b"]),
                rel("v1.1.0", [el("a", kind="library"), "b"]),
            )
        )

    assert chains(result)["LIN-a@v1.0.0"] == [("v1.0.0", "a")]
    assert lineage_of(result, "a", "v1.1.0").lineage_id == "LIN-a@v1.1.0"
    assert lineage_of(result, "a", "v1.1.0").kind == "library"
    [decision] = result.decisions
    assert (decision.method, decision.outcome) == (AlignMethod.EXACT, AlignOutcome.KIND_CHANGED)
    assert LINEAGE_KIND_CHANGED in reasons(logs)


# --- alias pass -------------------------------------------------------------------------------


def test_alias_rename_continues_the_lineage() -> None:
    result = track(
        timeline(
            rel("v1.0.0", ["a", "order-svc"]),
            rel("v1.1.0", ["a", el("order-service", aliases=["order-svc"])]),
        )
    )

    assert chains(result)["LIN-order-svc@v1.0.0"] == [
        ("v1.0.0", "order-svc"),
        ("v1.1.0", "order-service"),
    ]
    [event] = result.events
    assert event.lineage_id == "LIN-order-svc@v1.0.0"
    assert (event.event_type, event.method, event.release_id) == (
        LineageEventType.RENAME,
        AlignMethod.ALIAS,
        "v1.1.0",
    )
    assert (event.from_element_ids, event.to_element_ids) == (("order-svc",), ("order-service",))
    assert event.similarity is None
    [decision] = result.decisions
    assert (decision.method, decision.outcome) == (AlignMethod.ALIAS, AlignOutcome.LINKED)


def test_renames_chain_into_one_lineage_and_stale_aliases_are_ignored() -> None:
    result = track(
        timeline(
            rel("v1.0.0", ["a1"]),
            rel("v1.1.0", [el("a2", aliases=["a1"])]),
            rel("v1.2.0", [el("a3", aliases=["a2", "a1"])]),  # a1 is history, not a conflict
        )
    )

    assert list(chains(result)) == ["LIN-a1@v1.0.0"]
    assert [e.to_element_ids for e in result.events] == [("a2",), ("a3",)]


def test_alias_naming_an_id_that_still_exists_links_nothing() -> None:
    with capture_logs() as logs:
        result = track(
            timeline(
                rel("v1.0.0", ["a", "order-svc"], [("a", "order-svc")]),
                rel(
                    "v1.1.0",
                    ["a", "order-svc", el("order-service", aliases=["order-svc"])],
                    [("a", "order-svc"), ("a", "order-service")],
                ),
            )
        )

    assert lineage_of(result, "order-service", "v1.1.0").lineage_id == "LIN-order-service@v1.1.0"
    assert result.events == ()
    [decision] = result.decisions
    assert decision.outcome is AlignOutcome.ALIAS_CONFLICT
    assert ALIAS_CONFLICT in reasons(logs)


def test_alias_claimed_by_two_elements_links_neither() -> None:
    # A split: until splits are built (post-PP1) it breaks the lineage, and similarity may not
    # pick one of the two either.
    result = track(
        timeline(
            rel("v1.0.0", ["a", "monolith"], [("a", "monolith")]),
            rel(
                "v1.1.0",
                ["a", el("orders", aliases=["monolith"]), el("billing", aliases=["monolith"])],
                [("a", "orders")],
            ),
        )
    )

    assert chains(result)["LIN-monolith@v1.0.0"] == [("v1.0.0", "monolith")]
    assert result.events == ()
    [decision] = result.decisions
    assert decision.outcome is AlignOutcome.ALIAS_CONFLICT
    assert (decision.from_element_ids, decision.to_element_ids) == (
        ("monolith",),
        ("billing", "orders"),
    )


def test_element_with_two_disappeared_aliases_links_neither() -> None:
    result = track(
        timeline(
            rel("v1.0.0", ["orders", "billing"]),
            rel("v1.1.0", [el("commerce", aliases=["orders", "billing"])]),
        )
    )

    assert result.events == ()
    [decision] = result.decisions
    assert decision.outcome is AlignOutcome.ALIAS_CONFLICT
    assert (decision.from_element_ids, decision.to_element_ids) == (
        ("billing", "orders"),
        ("commerce",),
    )


def test_alias_rename_does_not_cross_a_kind_change() -> None:
    result = track(
        timeline(
            rel("v1.0.0", [el("order-svc", kind="service")]),
            rel("v1.1.0", [el("order-service", kind="library", aliases=["order-svc"])]),
        )
    )

    assert result.events == ()
    [decision] = result.decisions
    assert (decision.method, decision.outcome) == (AlignMethod.ALIAS, AlignOutcome.KIND_CHANGED)


# --- similarity pass --------------------------------------------------------------------------


def test_planted_rename_is_linked_by_similarity() -> None:
    result = track(SIMILARITY_RENAME)

    assert chains(result)["LIN-order-svc@v1.0.0"][-1] == ("v1.1.0", "order-service")
    [event] = result.events
    assert event.method is AlignMethod.SIMILARITY
    [decision] = result.decisions
    assert decision.outcome is AlignOutcome.LINKED
    assert decision.score is not None
    assert event.similarity == decision.score.total >= CFG.align.rename_min
    assert decision.runner_up is None  # no other candidate


def test_two_renames_in_one_release_are_both_linked() -> None:
    result = track(
        timeline(
            rel(
                "v1.0.0",
                ["a", "b", "c", "d", "order-svc", "pay-svc"],
                [("a", "order-svc"), ("order-svc", "b"), ("c", "pay-svc"), ("pay-svc", "d")],
            ),
            rel(
                "v1.1.0",
                ["a", "b", "c", "d", "order-service", "payment-service"],
                [
                    ("a", "order-service"),
                    ("order-service", "b"),
                    ("c", "payment-service"),
                    ("payment-service", "d"),
                ],
            ),
        )
    )

    renames = {(e.from_element_ids, e.to_element_ids) for e in result.events}
    assert renames == {(("order-svc",), ("order-service",)), (("pay-svc",), ("payment-service",))}


def test_two_equally_good_successors_are_ambiguous_and_not_linked() -> None:
    with capture_logs() as logs:
        result = track(
            timeline(
                rel(
                    "v1.0.0",
                    ["a", "b", el("billing-svc", name="billing")],
                    [("a", "billing-svc"), ("billing-svc", "b")],
                ),
                rel(
                    "v1.1.0",
                    ["a", "b", el("billing-a", name="billing"), el("billing-b", name="billing")],
                    [
                        ("a", "billing-a"),
                        ("billing-a", "b"),
                        ("a", "billing-b"),
                        ("billing-b", "b"),
                    ],
                ),
            )
        )

    assert chains(result)["LIN-billing-svc@v1.0.0"] == [("v1.0.0", "billing-svc")]
    assert result.events == ()
    [decision] = result.decisions
    assert decision.outcome is AlignOutcome.AMBIGUOUS
    assert decision.score is not None
    assert decision.runner_up == decision.score.total  # a tie: no margin at all
    assert ALIGNMENT_AMBIGUOUS in reasons(logs)


def test_two_equally_good_predecessors_are_ambiguous_and_not_linked() -> None:
    result = track(
        timeline(
            rel(
                "v1.0.0",
                ["a", "b", el("billing-a", name="billing"), el("billing-b", name="billing")],
                [("a", "billing-a"), ("billing-a", "b"), ("a", "billing-b"), ("billing-b", "b")],
            ),
            rel(
                "v1.1.0",
                ["a", "b", el("billing-svc", name="billing")],
                [("a", "billing-svc"), ("billing-svc", "b")],
            ),
        )
    )

    assert result.events == ()
    assert [d.outcome for d in result.decisions] == [AlignOutcome.AMBIGUOUS]


def test_unrelated_replacement_is_not_linked() -> None:
    result = track(
        timeline(
            rel("v1.0.0", ["a", "b", "legacy"], [("a", "legacy")]),
            rel("v1.1.0", ["a", "b", "payment"], [("b", "payment")]),
        )
    )

    assert result.events == ()
    [decision] = result.decisions
    assert decision.outcome is AlignOutcome.BELOW_MIN
    assert decision.score is not None
    assert decision.score.total < CFG.align.rename_min


def test_similarity_never_pairs_different_kinds() -> None:
    result = track(
        timeline(
            rel("v1.0.0", ["a", el("order-svc", kind="service")], [("a", "order-svc")]),
            rel("v1.1.0", ["a", el("order-service", kind="library")], [("a", "order-service")]),
        )
    )

    assert result.events == ()
    assert result.decisions == ()  # not candidates at all


def test_alignment_weights_come_from_config() -> None:
    # Same name, different neighbours: 0.4 * 1 + 0.4 * 0 + 0.2 * 1 = 0.6 by default.
    tl = timeline(
        rel("v1.0.0", ["a", "b", el("cart", name="cart")], [("a", "cart")]),
        rel("v1.1.0", ["a", "b", el("cart-v2", name="cart")], [("b", "cart-v2")]),
    )
    name_only = C3Config(align=AlignConfig(weights=AlignWeights(name=1, neighbours=0, size=0)))

    assert track(tl).events == ()
    assert [e.to_element_ids for e in track(tl, name_only).events] == [("cart-v2",)]


def test_rename_threshold_comes_from_config() -> None:
    strict = C3Config(align=AlignConfig(rename_min=0.99))

    result = track(SIMILARITY_RENAME, strict)

    assert result.events == ()
    assert [d.outcome for d in result.decisions] == [AlignOutcome.BELOW_MIN]


# --- whole runs -------------------------------------------------------------------------------


def test_result_does_not_depend_on_the_order_of_elements_or_edges() -> None:
    def build(reverse: bool) -> Timeline:
        def order(items: list[str]) -> list[str]:
            return sorted(items, reverse=reverse)

        return timeline(
            rel(
                "v1.0.0",
                order(["a", "b", "c", "order-svc"]),
                [("a", "order-svc"), ("order-svc", "b")],
            ),
            rel(
                "v1.1.0",
                order(["a", "b", "c", "order-service"]),
                [("order-service", "b"), ("a", "order-service")],
            ),
        )

    assert track(build(reverse=False)) == track(build(reverse=True))


@pytest.fixture(scope="module")
def stub_timeline() -> Timeline:
    files = StubService().generate().system_files
    service = IngestService(InMemoryReleaseRepository(), FixedClock(), CFG)
    service.ingest(
        RawPackage(source=name, data=text.encode("utf-8"))
        for name, text in sorted(files.items())
        if name.endswith(".json")
    )
    return service.timeline("shopfront")


def test_stub_rename_s4_is_one_lineage(stub_timeline: Timeline) -> None:
    truth = StubService().generate().ground_truth
    [rename] = truth.renames

    result = track(stub_timeline)

    n_releases = len(stub_timeline.entries)
    assert n_releases == 10
    assert len(result.lineages) == 15
    assert all(len(lin.members) == n_releases for lin in result.lineages)
    order = lineage_of(result, rename.to_id, rename.at_release)
    assert order.lineage_id == f"LIN-{rename.from_id}@v1.0.0"
    [event] = result.events
    assert (event.from_element_ids, event.to_element_ids, event.release_id) == (
        (rename.from_id,),
        (rename.to_id,),
        rename.at_release,
    )
    assert event.method is AlignMethod.ALIAS
    assert [d.outcome for d in result.decisions] == [AlignOutcome.LINKED]
