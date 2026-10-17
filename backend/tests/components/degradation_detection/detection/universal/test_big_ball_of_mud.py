"""BigBallOfMud: one system-scope instance when the largest SCC is large and modularity is low.

Presence only [D-24]. Whether the mud is getting worse is decided by the trend on
``largest_scc_share`` and ``modularity``, not by these thresholds.
"""

import pytest

from app.components.degradation_detection.config import BigBallOfMudConfig, DetectionConfig
from app.components.degradation_detection.detection.metric_registry import instance_measure
from app.components.degradation_detection.detection.models import ReleaseContext
from app.components.degradation_detection.detection.universal.big_ball_of_mud import (
    BigBallOfMud,
)
from app.domain.degradation_event import Scope, Worsening
from tests.components.degradation_detection.detection.graphs import release
from tests.components.degradation_detection.detection.universal.run import prepare

DETECTOR = BigBallOfMud()

# Two 3-cycles of equal size, c -> p joins them one way only.
TWIN_CYCLES = release(
    ["p", "q", "r", "a", "b", "c"],
    [("p", "q"), ("q", "r"), ("r", "p"), ("a", "b"), ("b", "c"), ("c", "a"), ("c", "p")],
)


def with_system(ctx: ReleaseContext, share: float, modularity: float | None) -> ReleaseContext:
    system = ctx.system_metrics | {"largest_scc_share": share, "modularity": modularity}
    return ctx.model_copy(update={"system_metrics": system})


def test_declaration() -> None:
    assert DETECTOR.id == "BigBallOfMud"
    assert DETECTOR.catalog == "universal"
    assert DETECTOR.styles == frozenset({"*"})
    assert DETECTOR.scope is Scope.SYSTEM
    assert DETECTOR.required_fields == frozenset()
    assert DETECTOR.driving_metrics == ("largest_scc_share", "modularity")
    assert DETECTOR.instance_measures == (
        instance_measure("largest_scc_share", "ratio"),
        instance_measure("modularity", "modularity", Worsening.DECREASE),
    )


def test_thresholds_are_inclusive() -> None:
    graph, ctx = prepare(TWIN_CYCLES)

    [instance] = DETECTOR.detect(graph, with_system(ctx, share=0.25, modularity=0.30))

    assert instance.scope is Scope.SYSTEM
    assert instance.local_instance_id == "BigBallOfMud:system"
    assert instance.measures == {"largest_scc_share": 0.25, "modularity": 0.30}


@pytest.mark.parametrize(
    ("share", "modularity"),
    [(0.24, 0.0), (1.0, 0.31), (1.0, None)],
    ids=["small", "modular", "null"],
)
def test_both_conditions_must_hold(share: float, modularity: float | None) -> None:
    graph, ctx = prepare(TWIN_CYCLES)

    assert DETECTOR.detect(graph, with_system(ctx, share, modularity)) == []


def test_thresholds_come_from_config() -> None:
    graph, ctx = prepare(
        TWIN_CYCLES,
        DetectionConfig(big_ball_of_mud=BigBallOfMudConfig(largest_scc_share_min=0.6)),
    )

    assert DETECTOR.detect(graph, with_system(ctx, share=0.5, modularity=0.0)) == []


def test_tied_largest_cycles_pick_the_one_with_the_smallest_member() -> None:
    graph, ctx = prepare(TWIN_CYCLES)

    [instance] = DETECTOR.detect(graph, with_system(ctx, share=0.5, modularity=0.0))

    assert instance.members == ("a", "b", "c")
