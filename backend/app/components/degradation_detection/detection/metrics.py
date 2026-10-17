"""M2 step 2: compute every declared metric for one release (pure).

Definitions are the plan's (Section 4, M2). Two rules shape the code:

- **Null stays null, never 0.** A metric is null when it is undefined for that element, not
  when it is small: ``instability`` of an isolated element (0/0), ``size_rz`` when MAD = 0,
  normalised fan when N = 1, ``unstable_dep_ratio`` with no out-deps, ``modularity`` with no
  edges. Counts that are genuinely zero stay 0: a DAG has ``largest_scc_size = 0``.
- **Relative to the release.** ``size_rz`` is a robust z within the release's own size
  distribution, so system-wide growth does not make every element look oversized.

Cycle measures come from strongly connected components [D-29]; simple cycles are never
enumerated (their number is exponential in the worst case).
"""

from collections.abc import Iterable, Sequence
from fractions import Fraction

import networkx as nx
import structlog
from networkx.algorithms.community import greedy_modularity_communities, modularity

from app.components.degradation_detection.detection import metric_registry as m
from app.components.degradation_detection.detection.metric_registry import (
    MetricRegistry,
    ap_count,
    is_anti_pattern_metric,
)
from app.components.degradation_detection.detection.models import (
    C1_METRIC_UNDECLARED,
    SIZE_UNIT_MIXED,
    ArchGraph,
)
from app.components.degradation_detection.detection.thresholds import robust_z
from app.components.degradation_detection.models import AntiPatternInstance, MetricObservation

log = structlog.get_logger(__name__)

C1_PREFIX = "c1."

Values = dict[str, float | None]


def compute_metrics(g: ArchGraph, registry: MetricRegistry) -> tuple[MetricObservation, ...]:
    """One observation per declared graph metric: per element, or once for a system metric.

    Anti-pattern counts are declared too but need the detectors' output: ``count_anti_patterns``.
    """
    element_values = _element_values(g)
    system_values = _system_values(g)
    _log_undeclared_c1(g, registry)

    observations: list[MetricObservation] = []
    for metric in registry.element_metrics:
        if metric.name.startswith(C1_PREFIX):
            values: Values = {e: g.element(e).metrics.get(metric.name) for e in g.nodes}
        elif metric.name in element_values:
            values = element_values[metric.name]
        else:
            raise ValueError(f"no computation for declared element metric {metric.name!r}")
        observations += (
            MetricObservation(
                release_id=g.release_id, element_id=e, metric=metric.name, value=values[e]
            )
            for e in g.nodes
        )
    for metric in registry.system_metrics:
        if is_anti_pattern_metric(metric.name):
            continue
        if metric.name not in system_values:
            raise ValueError(f"no computation for declared system metric {metric.name!r}")
        observations.append(
            MetricObservation(
                release_id=g.release_id,
                element_id=None,
                metric=metric.name,
                value=system_values[metric.name],
            )
        )
    return tuple(observations)


# --- element metrics ----------------------------------------------------------------------


def _element_values(g: ArchGraph) -> dict[str, Values]:
    fan_in = {e: len(g.predecessors(e)) for e in g.nodes}
    fan_out = {e: len(g.successors(e)) for e in g.nodes}
    # Exact fractions, so that 1/2 and 2/4 compare equal in unstable_dep_ratio.
    instability = {
        e: None if fan_in[e] + fan_out[e] == 0 else Fraction(fan_out[e], fan_in[e] + fan_out[e])
        for e in g.nodes
    }

    def normalised(fan: dict[str, int]) -> Values:
        return {e: None if g.n < 2 else fan[e] / (g.n - 1) for e in g.nodes}

    return {
        m.FAN_IN: {e: float(v) for e, v in fan_in.items()},
        m.FAN_OUT: {e: float(v) for e, v in fan_out.items()},
        m.FAN_IN_NORM: normalised(fan_in),
        m.FAN_OUT_NORM: normalised(fan_out),
        m.INSTABILITY: {e: None if v is None else float(v) for e, v in instability.items()},
        m.SIZE: {e: g.element(e).size for e in g.nodes},
        m.SIZE_RZ: _size_rz(g),
        m.SCC_SIZE: _scc_size(g),
        m.UNSTABLE_DEP_RATIO: {e: _unstable_dep_ratio(g, e, instability) for e in g.nodes},
    }


def _unstable_dep_ratio(
    g: ArchGraph, element_id: str, instability: dict[str, Fraction | None]
) -> float | None:
    """Share of out-deps on less stable elements: Martin's Stable Dependencies Principle."""
    targets = g.successors(element_id)
    own = instability[element_id]
    if not targets or own is None:  # own is None only for isolated elements, which have no targets
        return None
    worse = 0
    for target in targets:
        theirs = instability[target]  # has an in-edge, so never None
        if theirs is not None and theirs > own:
            worse += 1
    return worse / len(targets)


def _size_rz(g: ArchGraph) -> Values:
    """Robust z of size over the elements that have one, all in the same unit."""
    nulls: Values = dict.fromkeys(g.nodes)
    sized = {e: size for e in g.nodes if (size := g.element(e).size) is not None}
    if not sized:
        return nulls

    units = {g.element(e).size_unit for e in sized}
    if len(units) > 1:
        log.warning(
            SIZE_UNIT_MIXED,
            reason=SIZE_UNIT_MIXED,
            release_id=g.release_id,
            units=sorted(units, key=lambda unit: (unit is None, unit or "")),
        )
        return nulls

    z = robust_z(sized)  # None when MAD = 0: more than half the elements share one size
    if z is not None:
        nulls.update(z)
    return nulls


def strongly_connected(g: ArchGraph) -> list[frozenset[str]]:
    """All SCCs (singletons included), sorted by smallest member, independent of networkx order.

    Shared with the cycle detectors, so a cycle instance and ``scc_size`` are the same SCC.
    """
    return sorted((frozenset(c) for c in nx.strongly_connected_components(g.nx)), key=min)


def cyclic_components(g: ArchGraph) -> list[frozenset[str]]:
    """SCCs of two or more elements: each one contains a dependency cycle."""
    return [component for component in strongly_connected(g) if len(component) >= 2]


def _scc_size(g: ArchGraph) -> Values:
    return {e: float(len(component)) for component in strongly_connected(g) for e in component}


# --- system metrics -----------------------------------------------------------------------


def _system_values(g: ArchGraph) -> Values:
    cyclic = cyclic_components(g)
    component_of = {e: i for i, component in enumerate(cyclic) for e in component}
    largest = max((len(component) for component in cyclic), default=0)
    cyclic_edges = sum(
        1 for a, b in g.edges if a in component_of and component_of.get(b) == component_of[a]
    )
    return {
        m.SCC_COUNT: float(len(cyclic)),
        m.LARGEST_SCC_SIZE: float(largest),
        m.LARGEST_SCC_SHARE: largest / g.n,
        m.CYCLIC_EDGE_COUNT: float(cyclic_edges),
        m.MODULARITY: _modularity(g),
    }


def _modularity(g: ArchGraph) -> float | None:
    """Newman modularity of the greedy (Clauset-Newman-Moore) partition [D-27].

    Undirected and unweighted (owner decision, T-05): community structure is about which
    elements are coupled, not how often; A -> B and B -> A are one undirected edge. Greedy
    merging is deterministic for a fixed node order, and the graph is built in sorted order.
    """
    undirected: nx.Graph[str] = nx.Graph()
    undirected.add_nodes_from(g.nodes)
    undirected.add_edges_from(g.edges)
    if undirected.number_of_edges() == 0:  # modularity divides by the edge count
        return None
    communities = [set(c) for c in greedy_modularity_communities(undirected, weight=None)]
    return float(modularity(undirected, communities, weight=None))


# --- anti-pattern counts -----------------------------------------------------------------


def count_anti_patterns(
    g: ArchGraph,
    registry: MetricRegistry,
    detectors_run: Sequence[str],
    instances: Iterable[AntiPatternInstance],
) -> tuple[MetricObservation, ...]:
    """``ap_count.<Type>`` and ``ap_involvement_share`` of one release, in registry order.

    A count is 0 when its detector ran and found nothing, and null when it did not run (input
    missing, or not enabled for the style): an unchecked release is not a clean one.
    ``ap_involvement_share`` is the share of elements in at least one instance of the detectors
    that ran; null when none ran.
    """
    found = list(instances)
    values: Values = {}
    for anti_pattern_type in detectors_run:
        name = ap_count(anti_pattern_type)
        if name not in registry:
            raise ValueError(f"{anti_pattern_type} ran but {name} is not declared")
        values[name] = float(sum(1 for i in found if i.anti_pattern_type == anti_pattern_type))
    involved = {member for i in found for member in i.members}
    values[m.AP_INVOLVEMENT_SHARE] = len(involved) / g.n if detectors_run and g.n else None
    return tuple(
        MetricObservation(
            release_id=g.release_id,
            element_id=None,
            metric=metric.name,
            value=values.get(metric.name),
        )
        for metric in registry.anti_pattern_metrics
    )


# --- logging ------------------------------------------------------------------------------


def _log_undeclared_c1(g: ArchGraph, registry: MetricRegistry) -> None:
    supplied: Iterable[str] = {name for e in g.nodes for name in g.element(e).metrics}
    undeclared = sorted(name for name in supplied if name not in registry)
    if undeclared:
        # Not tested for a trend: C3 cannot know which direction is worse [D-21].
        log.info(
            C1_METRIC_UNDECLARED,
            reason=C1_METRIC_UNDECLARED,
            release_id=g.release_id,
            metrics=undeclared,
        )
