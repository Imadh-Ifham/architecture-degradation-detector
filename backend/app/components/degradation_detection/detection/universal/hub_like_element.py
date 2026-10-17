"""HubLikeElement: an element that many depend on *and* that depends on many (plan Section 4, M2).

Present when fan-in and fan-out are both above the release's upper IQR fence
(``Q3 + iqr_k * IQR``). Both, because high fan-in alone is a widely used, stable element (S3)
and high fan-out alone is an orchestrator; a hub concentrates change in both directions.

The fences use raw fan. Within one release the normalised fan is the raw fan divided by the same
N - 1, so the same elements are outliers; raw fan is always computed (normalised fan can be
switched off in config). The trend is tested on the normalised fan [D-04].
"""

from app.components.degradation_detection.detection import metric_registry as m
from app.components.degradation_detection.detection.models import (
    ArchGraph,
    ReleaseContext,
    local_instance_id,
)
from app.components.degradation_detection.detection.thresholds import upper_iqr_fence
from app.components.degradation_detection.models import AntiPatternInstance
from app.domain.degradation_event import Scope

DEGREE = "degree"


class HubLikeElement:
    id: str = "HubLikeElement"
    catalog: str = "universal"
    styles: frozenset[str] = frozenset({"*"})
    scope: Scope = Scope.ELEMENT
    required_fields: frozenset[str] = frozenset()
    driving_metrics: tuple[str, ...] = (m.FAN_IN_NORM, m.FAN_OUT_NORM)
    instance_measures: tuple[str, ...] = (DEGREE,)

    def detect(self, g: ArchGraph, ctx: ReleaseContext) -> list[AntiPatternInstance]:
        fan_in = _counts(ctx.element_values(m.FAN_IN))
        fan_out = _counts(ctx.element_values(m.FAN_OUT))
        k = ctx.cfg.hub.iqr_k
        in_fence = upper_iqr_fence(fan_in.values(), k)
        out_fence = upper_iqr_fence(fan_out.values(), k)
        if in_fence is None or out_fence is None:  # fewer than two elements
            return []
        return [
            AntiPatternInstance(
                release_id=g.release_id,
                local_instance_id=local_instance_id(self.id, e),
                anti_pattern_type=self.id,
                catalog=self.catalog,
                scope=self.scope,
                members=(e,),
                measures={DEGREE: fan_in[e] + fan_out[e]},
            )
            for e in g.nodes  # sorted
            if fan_in[e] > in_fence and fan_out[e] > out_fence
        ]


def _counts(values: dict[str, float | None]) -> dict[str, float]:
    """Fan is a count and is never null; a null here is a bug in metrics.py, not missing data."""
    counts = {e: value for e, value in values.items() if value is not None}
    if len(counts) != len(values):
        raise ValueError("fan counts must not be null")
    return counts
