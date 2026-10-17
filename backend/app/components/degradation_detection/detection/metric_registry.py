"""M2 step 2: the metric registry. Every metric is declared once, here (plan Section 4, M2).

A declaration says which level a metric lives at and in which direction it gets worse. M4 needs
the direction to turn a significant trend into a worsening one, so it lives next to the
definition instead of being guessed later. ``worsening = None`` marks a metric that only
supports detectors (``instability``) and is never tested for a trend on its own.

``metrics.py`` computes exactly the declared metrics: a declared metric without a computation
is an error there, so the registry and the computed observations cannot drift apart.

Anti-pattern counts (``ap_count.<Type>``, ``ap_involvement_share``) count the output of the
detectors, so they are declared for the anti-pattern types the detector registry can run and
computed after detection (``metrics.count_anti_patterns``), not from the graph.
"""

from collections.abc import Iterable, Sequence

from app.components.degradation_detection.config import MetricsConfig
from app.components.degradation_detection.models import (
    AP_INVOLVEMENT_SHARE,
    MetricDef,
    MetricLevel,
    ap_count,
    is_anti_pattern_metric,
)
from app.domain.degradation_event import Worsening

# Element level
FAN_IN = "fan_in"
FAN_OUT = "fan_out"
FAN_IN_NORM = "fan_in_norm"
FAN_OUT_NORM = "fan_out_norm"
INSTABILITY = "instability"
SIZE = "size"
SIZE_RZ = "size_rz"
SCC_SIZE = "scc_size"
UNSTABLE_DEP_RATIO = "unstable_dep_ratio"

# System level
SCC_COUNT = "scc_count"
LARGEST_SCC_SIZE = "largest_scc_size"
LARGEST_SCC_SHARE = "largest_scc_share"
CYCLIC_EDGE_COUNT = "cyclic_edge_count"
MODULARITY = "modularity"

# System level, from the detectors' output: ``ap_count(<Type>)`` and ``AP_INVOLVEMENT_SHARE``,
# named in the component models because the series builder and M4 read those names too.

_UP = Worsening.INCREASE


def _element(name: str, unit: str, worsening: Worsening | None = _UP) -> MetricDef:
    return MetricDef(name=name, level=MetricLevel.ELEMENT, unit=unit, worsening=worsening)


def _system(name: str, unit: str, worsening: Worsening = _UP) -> MetricDef:
    return MetricDef(name=name, level=MetricLevel.SYSTEM, unit=unit, worsening=worsening)


class MetricRegistry:
    """An ordered set of metric declarations; the order is the order observations come out in."""

    def __init__(self, defs: Iterable[MetricDef]) -> None:
        self._defs: dict[str, MetricDef] = {}
        for metric in defs:
            if metric.name in self._defs:
                raise ValueError(f"metric {metric.name!r} is declared twice")
            self._defs[metric.name] = metric

    @classmethod
    def from_config(
        cls, cfg: MetricsConfig, anti_pattern_types: Sequence[str] = ()
    ) -> "MetricRegistry":
        """The plan's metrics, plus anti-pattern counts when there are detectors to count."""
        anti_patterns = [_system(ap_count(t), "count") for t in anti_pattern_types]
        if anti_patterns:
            anti_patterns.append(_system(AP_INVOLVEMENT_SHARE, "ratio"))
        coupling = [_element(FAN_IN, "count"), _element(FAN_OUT, "count")]
        if cfg.normalised_coupling:  # [D-04] primary coupling measure for cross-style results
            coupling += [_element(FAN_IN_NORM, "ratio"), _element(FAN_OUT_NORM, "ratio")]
        return cls(
            [
                *coupling,
                _element(INSTABILITY, "ratio", worsening=None),
                _element(SIZE, "size_unit"),  # whatever unit C1 reports in element.size_unit
                _element(SIZE_RZ, "robust_z"),
                _element(SCC_SIZE, "count"),
                _element(UNSTABLE_DEP_RATIO, "ratio"),
                *(_element(m.name, m.unit, m.worsening) for m in cfg.c1_passthrough),  # [D-21]
                _system(SCC_COUNT, "count"),
                _system(LARGEST_SCC_SIZE, "count"),
                _system(LARGEST_SCC_SHARE, "ratio"),
                _system(CYCLIC_EDGE_COUNT, "count"),
                _system(MODULARITY, "modularity", worsening=Worsening.DECREASE),
                *anti_patterns,
            ]
        )

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._defs)

    @property
    def element_metrics(self) -> tuple[MetricDef, ...]:
        return tuple(d for d in self._defs.values() if d.level is MetricLevel.ELEMENT)

    @property
    def system_metrics(self) -> tuple[MetricDef, ...]:
        return tuple(d for d in self._defs.values() if d.level is MetricLevel.SYSTEM)

    @property
    def anti_pattern_metrics(self) -> tuple[MetricDef, ...]:
        """System metrics computed from the detectors' output instead of from the graph."""
        return tuple(d for d in self.system_metrics if is_anti_pattern_metric(d.name))

    def get(self, name: str) -> MetricDef:
        try:
            return self._defs[name]
        except KeyError:
            raise KeyError(f"metric {name!r} is not declared") from None

    def __contains__(self, name: object) -> bool:
        return name in self._defs
