"""UnstableDependency: an element that depends on elements less stable than itself.

Martin's Stable Dependencies Principle: depend in the direction of stability. Instability is
``I = fan_out / (fan_in + fan_out)``; an edge e -> t is *bad* when ``I(t) > I(e)``. Present
when the share of bad out-edges (``unstable_dep_ratio``) is at least the configured ratio.

The instance is the element alone (owner decision, T-06). Its bad targets are counted in
``bad_edge_count`` but are not members, so the instance keeps one identity across releases
while it picks up more bad dependencies, which is exactly the worsening M4 should see.
"""

from app.components.degradation_detection.detection import metric_registry as m
from app.components.degradation_detection.detection.models import (
    ArchGraph,
    ReleaseContext,
    local_instance_id,
)
from app.components.degradation_detection.models import AntiPatternInstance
from app.domain.degradation_event import Scope

BAD_EDGE_COUNT = "bad_edge_count"


class UnstableDependency:
    id: str = "UnstableDependency"
    catalog: str = "universal"
    styles: frozenset[str] = frozenset({"*"})
    scope: Scope = Scope.ELEMENT
    required_fields: frozenset[str] = frozenset()
    driving_metrics: tuple[str, ...] = (m.UNSTABLE_DEP_RATIO,)
    instance_measures: tuple[str, ...] = (BAD_EDGE_COUNT,)

    def detect(self, g: ArchGraph, ctx: ReleaseContext) -> list[AntiPatternInstance]:
        ratio = ctx.element_values(m.UNSTABLE_DEP_RATIO)
        instability = ctx.element_values(m.INSTABILITY)
        threshold = ctx.cfg.unstable.ratio
        instances = []
        for e in g.nodes:  # sorted
            value = ratio[e]
            if value is None or value < threshold:  # None: no out-deps, nothing to judge
                continue
            instances.append(
                AntiPatternInstance(
                    release_id=g.release_id,
                    local_instance_id=local_instance_id(self.id, e),
                    anti_pattern_type=self.id,
                    catalog=self.catalog,
                    scope=self.scope,
                    members=(e,),
                    measures={BAD_EDGE_COUNT: float(_bad_edges(g, e, instability))},
                )
            )
        return instances


def _bad_edges(g: ArchGraph, e: str, instability: dict[str, float | None]) -> int:
    own = instability[e]
    if own is None:  # isolated: no edges at all
        return 0
    return sum(
        1 for t in g.successors(e) if (theirs := instability[t]) is not None and theirs > own
    )
