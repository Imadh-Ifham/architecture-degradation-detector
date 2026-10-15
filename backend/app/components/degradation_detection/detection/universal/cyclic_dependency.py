"""CyclicDependency: elements that depend on each other in a loop (plan Section 4, M2).

One instance per strongly connected component (Tarjan) of two or more elements. An SCC is the
maximal set in which every element reaches every other, so one instance covers all the cycles
through those elements instead of enumerating them (their number is exponential [D-29]).
"""

from app.components.degradation_detection.detection import metric_registry as m
from app.components.degradation_detection.detection.metrics import cyclic_components
from app.components.degradation_detection.detection.models import (
    ArchGraph,
    ReleaseContext,
    local_instance_id,
)
from app.components.degradation_detection.models import AntiPatternInstance
from app.domain.degradation_event import Scope

MEMBER_COUNT = "member_count"
INTERNAL_EDGE_COUNT = "internal_edge_count"


class CyclicDependency:
    id: str = "CyclicDependency"
    catalog: str = "universal"
    styles: frozenset[str] = frozenset({"*"})
    scope: Scope = Scope.INSTANCE
    required_fields: frozenset[str] = frozenset()
    driving_metrics: tuple[str, ...] = (m.SCC_SIZE,)
    instance_measures: tuple[str, ...] = (MEMBER_COUNT, INTERNAL_EDGE_COUNT)

    def detect(self, g: ArchGraph, ctx: ReleaseContext) -> list[AntiPatternInstance]:
        instances = []
        for component in cyclic_components(g):  # sorted by smallest member
            members = tuple(sorted(component))
            internal = sum(1 for a, b in g.edges if a in component and b in component)
            instances.append(
                AntiPatternInstance(
                    release_id=g.release_id,
                    local_instance_id=local_instance_id(self.id, members[0]),
                    anti_pattern_type=self.id,
                    catalog=self.catalog,
                    scope=self.scope,
                    members=members,
                    measures={
                        MEMBER_COUNT: float(len(members)),
                        INTERNAL_EDGE_COUNT: float(internal),
                    },
                )
            )
        return instances
