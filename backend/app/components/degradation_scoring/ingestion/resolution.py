# Matches each event's element names to graph nodes (C4-ADR-007 A3/A4).
# Order per name: node id -> alias -> folder prefix of exactly one node's source paths.
# An event is resolved only if every name resolves; otherwise it is quarantined.

from collections.abc import Sequence

import networkx as nx
import structlog

from app.components.degradation_scoring.ingestion.models import ResolvedEvent
from app.domain.degradation_event import DegradationEventV2
from app.domain.severity_report import (
    QuarantinedEvent,
    QuarantineReason,
    Resolution,
    ResolutionStatus,
)

log = structlog.get_logger(__name__)

EXACT_CONFIDENCE = 1.0


def resolve_events(
    events: Sequence[DegradationEventV2],
    graph: "nx.DiGraph[str]",
    *,
    prefix_confidence: float,
) -> tuple[list[ResolvedEvent], list[QuarantinedEvent], float]:
    # Returns resolved events, quarantined ones, and resolution_rate = resolved / eligible
    # (1.0 when there is nothing to resolve: no resolution failed).
    aliases = _alias_index(graph)
    resolved: list[ResolvedEvent] = []
    quarantined: list[QuarantinedEvent] = []
    for event in events:
        names = [event.element_id] if event.element_id else list(event.members)
        nodes: set[str] = set()
        used_prefix = False
        problems: list[str] = []
        for name in names:
            matches, via_prefix = _match(name, graph, aliases)
            if len(matches) == 1:
                nodes |= matches
                used_prefix |= via_prefix
            elif matches:
                problems.append(f"ambiguous: {name} (matches {len(matches)} nodes)")
            else:
                problems.append(f"missing: {name}")
        if problems or not nodes:
            quarantined.append(_unresolved(event, problems or ["event names no element"]))
            continue
        status = ResolutionStatus.PREFIX_FALLBACK if used_prefix else ResolutionStatus.EXACT
        confidence = prefix_confidence if used_prefix else EXACT_CONFIDENCE
        resolved.append(
            ResolvedEvent(
                event=event,
                nodes=sorted(nodes),
                resolution=Resolution(status=status, confidence=confidence),
            )
        )
    rate = len(resolved) / len(events) if events else 1.0
    return resolved, quarantined, rate


def _alias_index(graph: "nx.DiGraph[str]") -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    for node, aliases in graph.nodes(data="aliases", default=[]):
        for alias in aliases:
            index.setdefault(alias, set()).add(node)
    return index


def _match(
    name: str, graph: "nx.DiGraph[str]", aliases: dict[str, set[str]]
) -> tuple[set[str], bool]:
    # Returns the matching nodes and whether they were found through the path prefix.
    if name in graph:
        return {name}, False
    if name in aliases:
        return aliases[name], False
    folder = name.rstrip("/") + "/"
    by_path = {
        node
        for node, paths in graph.nodes(data="source_paths", default=[])
        if any(path.startswith(folder) for path in paths)
    }
    return by_path, True


def _unresolved(event: DegradationEventV2, problems: list[str]) -> QuarantinedEvent:
    detail = "; ".join(problems)
    reason = QuarantineReason.UNRESOLVED_ELEMENT
    log.warning("event_quarantined", reason=str(reason), event_id=event.event_id, detail=detail)
    return QuarantinedEvent(event_id=event.event_id, reason=reason, detail=detail)
