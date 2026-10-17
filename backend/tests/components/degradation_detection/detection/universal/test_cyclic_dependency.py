"""CyclicDependency: one instance per strongly connected component of two or more elements."""

from app.components.degradation_detection.detection.metric_registry import instance_measure
from app.components.degradation_detection.detection.universal.cyclic_dependency import (
    CyclicDependency,
)
from app.domain.degradation_event import Scope
from tests.components.degradation_detection.detection.graphs import TWO_TRIANGLES, release
from tests.components.degradation_detection.detection.universal.run import run

DETECTOR = CyclicDependency()


def test_declaration() -> None:
    assert DETECTOR.id == "CyclicDependency"
    assert DETECTOR.catalog == "universal"
    assert DETECTOR.styles == frozenset({"*"})
    assert DETECTOR.scope is Scope.INSTANCE
    assert DETECTOR.required_fields == frozenset()
    assert DETECTOR.driving_metrics == ("scc_size",)
    assert DETECTOR.instance_measures == (
        instance_measure("member_count", "count"),
        instance_measure("internal_edge_count", "count"),
    )


def test_two_separate_cycles_are_two_instances_in_member_order() -> None:
    edges = [("p", "q"), ("q", "p"), ("a", "b"), ("b", "c"), ("c", "a"), ("c", "p")]

    found = run(release(["q", "p", "c", "b", "a"], edges), [DETECTOR])

    assert [i.members for i in found] == [("a", "b", "c"), ("p", "q")]
    assert [i.local_instance_id for i in found] == ["CyclicDependency:a", "CyclicDependency:p"]


def test_internal_edges_exclude_edges_leaving_the_cycle() -> None:
    # Two triangles joined by c -> d: two cycles, the bridge belongs to neither.
    found = run(release("abcdef", TWO_TRIANGLES), [DETECTOR])

    assert [i.measures for i in found] == [
        {"member_count": 3.0, "internal_edge_count": 3.0},
        {"member_count": 3.0, "internal_edge_count": 3.0},
    ]


def test_dag_has_no_cycle() -> None:
    assert run(release("abc", [("a", "b"), ("b", "c"), ("a", "c")]), [DETECTOR]) == []
