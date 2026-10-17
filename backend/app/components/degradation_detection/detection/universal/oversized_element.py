"""OversizedElement (a.k.a. God Component): an element far larger than the rest of its release.

Present when ``size_rz``, the robust z of size within the release, is above ``z_max``. Relative
to the release, so a system that grows evenly does not make its elements oversized. A null
``size_rz`` (unknown size, mixed units, MAD = 0) never makes an element oversized.
"""

from app.components.degradation_detection.detection import metric_registry as m
from app.components.degradation_detection.detection.models import (
    ArchGraph,
    ReleaseContext,
    local_instance_id,
)
from app.components.degradation_detection.models import AntiPatternInstance
from app.domain.degradation_event import Scope


class OversizedElement:
    id: str = "OversizedElement"
    catalog: str = "universal"
    styles: frozenset[str] = frozenset({"*"})
    scope: Scope = Scope.ELEMENT
    required_fields: frozenset[str] = frozenset()
    driving_metrics: tuple[str, ...] = (m.SIZE_RZ,)
    instance_measures: tuple[str, ...] = (m.SIZE_RZ,)

    def detect(self, g: ArchGraph, ctx: ReleaseContext) -> list[AntiPatternInstance]:
        size_rz = ctx.element_values(m.SIZE_RZ)
        z_max = ctx.cfg.oversized.z_max
        instances = []
        for e in g.nodes:  # sorted
            z = size_rz[e]
            if z is None or z <= z_max:
                continue
            instances.append(
                AntiPatternInstance(
                    release_id=g.release_id,
                    local_instance_id=local_instance_id(self.id, e),
                    anti_pattern_type=self.id,
                    catalog=self.catalog,
                    scope=self.scope,
                    members=(e,),
                    measures={m.SIZE_RZ: z},
                )
            )
        return instances
