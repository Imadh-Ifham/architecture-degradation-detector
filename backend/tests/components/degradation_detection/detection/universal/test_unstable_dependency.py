"""UnstableDependency: an element whose share of out-deps on less stable elements is too high."""

from app.components.degradation_detection.config import DetectionConfig, UnstableConfig
from app.components.degradation_detection.detection.universal.unstable_dependency import (
    UnstableDependency,
)
from app.domain.degradation_event import Scope
from tests.components.degradation_detection.detection.graphs import release
from tests.components.degradation_detection.detection.universal.run import run

DETECTOR = UnstableDependency()

# g has instability 1/2 and depends on u (2/3, less stable) and z (0): ratio 1/2, one bad edge.
GATEWAY = release(
    ["g", "u", "x1", "x2", "y1", "y2", "z"],
    [("x1", "g"), ("x2", "g"), ("g", "u"), ("g", "z"), ("u", "y1"), ("u", "y2")],
)


def test_declaration() -> None:
    assert DETECTOR.id == "UnstableDependency"
    assert DETECTOR.catalog == "universal"
    assert DETECTOR.styles == frozenset({"*"})
    assert DETECTOR.scope is Scope.ELEMENT
    assert DETECTOR.required_fields == frozenset()
    assert DETECTOR.driving_metrics == ("unstable_dep_ratio",)
    assert DETECTOR.instance_measures == ("bad_edge_count",)


def test_members_are_the_element_alone() -> None:
    # Owner decision (T-06): the bad targets are counted, not members, so the instance keeps its
    # identity while the element picks up more bad dependencies.
    [instance] = run(GATEWAY, [DETECTOR])

    assert instance.members == ("g",)
    assert instance.local_instance_id == "UnstableDependency:g"
    assert instance.measures == {"bad_edge_count": 1.0}


def test_ratio_threshold_is_inclusive_and_from_config() -> None:
    at = DetectionConfig(unstable=UnstableConfig(ratio=0.5))
    above = DetectionConfig(unstable=UnstableConfig(ratio=0.51))

    assert len(run(GATEWAY, [DETECTOR], cfg=at)) == 1
    assert run(GATEWAY, [DETECTOR], cfg=above) == []


def test_bad_edges_are_counted_per_target() -> None:
    # a (2 out of 5 = 2/5) depends on b and c, both with instability 1/2: two bad edges of two.
    callers = [("w", "a"), ("x", "a"), ("y", "a")]
    r = release("abcwxyz", [*callers, ("a", "b"), ("a", "c"), ("b", "z"), ("c", "z")])

    [instance] = run(r, [DETECTOR])

    assert instance.members == ("a",)
    assert instance.measures == {"bad_edge_count": 2.0}


def test_equal_instability_is_not_a_bad_edge() -> None:
    # Every element of a plain cycle has instability 1/2.
    assert run(release("abc", [("a", "b"), ("b", "c"), ("c", "a")]), [DETECTOR]) == []
