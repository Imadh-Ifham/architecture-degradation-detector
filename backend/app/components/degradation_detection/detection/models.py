"""M2 models: the graph of one release, what detectors read, the detector interface, reason codes.

``MetricDef`` / ``MetricObservation`` / ``AntiPatternInstance`` are in the component
``models.py``, because M3 and M4 read them too.
"""

# networkx is generic only in its type stubs: keep ``nx.DiGraph[str]`` unevaluated at runtime.
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol

import networkx as nx

from app.components.degradation_detection.config import DetectionConfig
from app.components.degradation_detection.models import (
    AntiPatternInstance,
    InternalModel,
    MetricObservation,
)
from app.domain.canonical_release import DatastoreAccess, ElementSnapshot
from app.domain.degradation_event import Scope

# Reason codes M2 logs. Nothing is rejected: a metric that cannot be computed is null.
C1_METRIC_UNDECLARED = "C1_METRIC_UNDECLARED"  # C1 sent a metric config does not declare
SIZE_UNIT_MIXED = "SIZE_UNIT_MIXED"  # sizes in different units: size_rz is null
CATALOG_INPUT_MISSING = "CATALOG_INPUT_MISSING"  # detector skipped: optional package field absent


class ArchGraph:
    """The dependency graph of one release, read-only.

    One node per element (isolated elements included), one edge per ordered pair with the
    dependency ``types`` and ``weight = count``. Nodes and edges were inserted in sorted order,
    so every networkx algorithm sees the same graph whatever order C2 wrote the package in.
    ``nx`` is frozen: detectors may run algorithms on it but never change it.

    ``datastore_access`` is the release's optional field as M1 stored it: None when C2 did not
    send it, which is different from an empty tuple (C2 found no datastores).
    """

    def __init__(
        self,
        release_id: str,
        graph: nx.DiGraph[str],
        elements: Mapping[str, ElementSnapshot],
        datastore_access: tuple[DatastoreAccess, ...] | None = None,
    ) -> None:
        self._release_id = release_id
        self._datastore_access = datastore_access
        nx.freeze(graph)  # in place: any later mutation raises NetworkXError
        self._graph = graph
        self._elements = dict(elements)
        self._nodes = tuple(graph.nodes)
        self._edges: tuple[tuple[str, str], ...] = tuple(graph.edges)

    @property
    def release_id(self) -> str:
        return self._release_id

    @property
    def nx(self) -> nx.DiGraph[str]:
        return self._graph

    @property
    def nodes(self) -> tuple[str, ...]:
        return self._nodes

    @property
    def n(self) -> int:
        return len(self._nodes)

    @property
    def edges(self) -> tuple[tuple[str, str], ...]:
        return self._edges

    @property
    def datastore_access(self) -> tuple[DatastoreAccess, ...] | None:
        return self._datastore_access

    def element(self, element_id: str) -> ElementSnapshot:
        return self._elements[element_id]

    def successors(self, element_id: str) -> tuple[str, ...]:
        """Distinct elements this one depends on, sorted."""
        return tuple(sorted(self._graph.successors(element_id)))

    def predecessors(self, element_id: str) -> tuple[str, ...]:
        """Distinct elements that depend on this one, sorted."""
        return tuple(sorted(self._graph.predecessors(element_id)))


class ReleaseContext(InternalModel):
    """What a detector may read besides the graph: the release's metrics and the thresholds.

    Detectors read metrics instead of recomputing them, so the value that makes an anti-pattern
    present is the same value M3 puts in the series that M4 tests for a trend.
    """

    cfg: DetectionConfig
    element_metrics: dict[str, dict[str, float | None]]  # metric -> element -> value
    system_metrics: dict[str, float | None]  # metric -> value

    @classmethod
    def from_observations(
        cls, observations: Iterable[MetricObservation], cfg: DetectionConfig
    ) -> ReleaseContext:
        element: dict[str, dict[str, float | None]] = {}
        system: dict[str, float | None] = {}
        for o in observations:
            if o.element_id is None:
                system[o.metric] = o.value
            else:
                element.setdefault(o.metric, {})[o.element_id] = o.value
        return cls(cfg=cfg, element_metrics=element, system_metrics=system)

    def element_values(self, metric: str) -> dict[str, float | None]:
        """Value per element; a KeyError means the detector needs a metric that was not computed."""
        try:
            return self.element_metrics[metric]
        except KeyError:
            raise KeyError(f"element metric {metric!r} was not computed") from None

    def system_value(self, metric: str) -> float | None:
        try:
            return self.system_metrics[metric]
        except KeyError:
            raise KeyError(f"system metric {metric!r} was not computed") from None


class AntiPatternDetector(Protocol):
    """One anti-pattern as a fitness function over a release's graph (plan Section 4, M2 step 3).

    A detector says whether the anti-pattern is *present* in one release. Whether it is getting
    *worse* is never its call: that is M4's trend test on ``driving_metrics`` (element and
    system series) and ``instance_measures`` (the series M3 builds per instance track).
    Thresholds are read from ``ctx.cfg`` and are relative to the release, never constants.
    """

    id: str  # the anti_pattern_type it emits, e.g. "CyclicDependency"
    catalog: str  # "universal" | "microservices" | "layered"
    styles: frozenset[str]  # {"*"} or the architecture styles it applies to (registry, T-07)
    scope: Scope
    required_fields: frozenset[str]  # optional package fields it needs, e.g. "datastore_access"
    driving_metrics: tuple[str, ...]
    instance_measures: tuple[str, ...]  # exactly the keys of every instance's ``measures``

    def detect(self, g: ArchGraph, ctx: ReleaseContext) -> list[AntiPatternInstance]: ...


def local_instance_id(anti_pattern_type: str, key: str) -> str:
    """Instance id within one release, e.g. ``CyclicDependency:inventory``.

    Keyed on content (the smallest member, or the shared datastore), not on discovery order, so
    it is stable for a given graph. It is not an identity across releases: M3 assigns
    ``AP-<TYPE>-NNNN`` track ids.
    """
    return f"{anti_pattern_type}:{key}"
