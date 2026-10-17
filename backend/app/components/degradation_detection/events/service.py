"""M6 Event Emitter (plan Section 4, M6). PP1: export only.

Turns M4's event candidates into ``DegradationEventV2`` (the C3 -> C4 contract), checks every
one against the contract's JSON Schema and returns the ``events.json`` text; the caller writes
it. PP1 runs with context disabled [D-28], so every event is ``GENUINE`` at stage ``DISABLED``
and ``PENDING`` review: the trend-only baseline.

Post-PP1: immutable rows, ``supersedes_event_id`` for a longer window of the same
``event_key``, and the ``c3.event.emitted`` outbox message.
"""

from collections.abc import Iterable

from app.components.degradation_detection.config import C3Config
from app.components.degradation_detection.events.emitter import (
    check_against_schema,
    events_json,
    to_event,
)
from app.components.degradation_detection.events.models import EventExport
from app.components.degradation_detection.models import EventCandidate, Timeline


class EventService:
    def __init__(self, cfg: C3Config) -> None:
        self._cfg = cfg

    def emit(
        self, candidates: Iterable[EventCandidate], timeline: Timeline, run_id: str
    ) -> EventExport:
        """One event per candidate, in candidate order."""
        if self._cfg.context.enabled:
            raise NotImplementedError("context.enabled needs M5 (post-PP1); run with it off")
        events = tuple(
            to_event(c, timeline, run_id=run_id, config_hash=self._cfg.config_hash)
            for c in candidates
        )
        payload = [event.model_dump(mode="json") for event in events]
        check_against_schema(payload)
        return EventExport(events=events, text=events_json(payload))
