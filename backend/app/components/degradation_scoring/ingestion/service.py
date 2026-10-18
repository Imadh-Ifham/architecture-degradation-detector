# Ingestion: validates C3 events and decides which are ranked
# Element resolution (T10) and ADR loading (T16) join this entry point later.

from collections.abc import Iterable

from app.components.degradation_scoring.config import C4Config
from app.components.degradation_scoring.ingestion.events import ingest_events
from app.components.degradation_scoring.ingestion.models import EventIngestion


class IngestionService:
    """Turns raw C3 payloads into eligible events plus quarantine and skip lists."""

    def __init__(self, config: C4Config) -> None:
        self._config = config

    def ingest(self, payloads: Iterable[object]) -> EventIngestion:
        return ingest_events(payloads, rank_only_confirmed=self._config.rank_only_confirmed)
