# Ingestion: validates C3 events, decides which are ranked, resolves them to graph nodes and
# parses the ADR index when there is one (T16).

from collections.abc import Iterable

import networkx as nx

from app.components.degradation_scoring.config import C4Config
from app.components.degradation_scoring.ingestion.adr import parse_index
from app.components.degradation_scoring.ingestion.events import ingest_events
from app.components.degradation_scoring.ingestion.models import IngestionResult
from app.components.degradation_scoring.ingestion.resolution import resolve_events


class IngestionService:
    # Turns raw C3 payloads plus the release graph into events ready to score.

    def __init__(self, config: C4Config) -> None:
        self._config = config

    def ingest(
        self,
        payloads: Iterable[object],
        graph: "nx.DiGraph[str]",
        adr_document: object | None = None,
    ) -> IngestionResult:
        # adr_document None = no ADR index for this run (the ADR-violation criterion is off)
        events = ingest_events(payloads, rank_only_confirmed=self._config.rank_only_confirmed)
        resolved, unresolved, rate = resolve_events(
            events.eligible, graph, prefix_confidence=self._config.resolution_prefix_confidence
        )
        return IngestionResult(
            eligible=events.eligible,
            resolved=resolved,
            quarantined=[*events.quarantined, *unresolved],
            skipped=events.skipped,
            resolution_rate=rate,
            adr_index=parse_index(adr_document) if adr_document is not None else None,
        )
