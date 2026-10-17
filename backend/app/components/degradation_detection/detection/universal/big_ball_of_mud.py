"""BigBallOfMud: the system as a whole has lost its structure (plan Section 4, M2; R11).

One system-scope instance when a large share of the elements sit in one dependency tangle
(``largest_scc_share >= largest_scc_share_min``) **and** the graph has little community
structure (``modularity <= modularity_max``) [D-24]. Members are the largest SCC.

These thresholds only decide *presence*. Whether the mud is getting worse is M4's call, on the
``largest_scc_share`` (up) and ``modularity`` (down) series, so S8 is reported as a trend even in
releases where this detector does not fire.
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

SYSTEM_KEY = "system"


class BigBallOfMud:
    id: str = "BigBallOfMud"
    catalog: str = "universal"
    styles: frozenset[str] = frozenset({"*"})
    scope: Scope = Scope.SYSTEM
    required_fields: frozenset[str] = frozenset()
    driving_metrics: tuple[str, ...] = (m.LARGEST_SCC_SHARE, m.MODULARITY)
    instance_measures: tuple[str, ...] = (m.LARGEST_SCC_SHARE, m.MODULARITY)

    def detect(self, g: ArchGraph, ctx: ReleaseContext) -> list[AntiPatternInstance]:
        share = ctx.system_value(m.LARGEST_SCC_SHARE)
        modularity = ctx.system_value(m.MODULARITY)
        cfg = ctx.cfg.big_ball_of_mud
        if share is None or modularity is None:  # modularity is null when there are no edges
            return []
        if share < cfg.largest_scc_share_min or modularity > cfg.modularity_max:
            return []
        cycles = cyclic_components(g)
        if not cycles:  # only reachable with a minimum share of 0
            return []
        # Ties: max() keeps the first, and the components are sorted by smallest member.
        largest = max(cycles, key=len)
        return [
            AntiPatternInstance(
                release_id=g.release_id,
                local_instance_id=local_instance_id(self.id, SYSTEM_KEY),
                anti_pattern_type=self.id,
                catalog=self.catalog,
                scope=self.scope,
                members=tuple(sorted(largest)),
                measures={m.LARGEST_SCC_SHARE: share, m.MODULARITY: modularity},
            )
        ]
