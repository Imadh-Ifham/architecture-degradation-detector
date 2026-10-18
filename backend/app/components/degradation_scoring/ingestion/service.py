"""Ingestion service.

Author: Dahami
Date: 2026-10-14
Description:
    Validates C3 degradation events and quarantines malformed, non-confirmed
    and intentional ones; resolves event elements to graph nodes; parses ADR
    index entries. Implements CLAUDE.md §4.1, §5.1 (resolution) and §5.3
    (ADR loading).

    Scaffold only (C4-T02): the public entry method is added by C4-T08.
"""


class IngestionService:
    """Turns raw C3 events into validated, resolved events plus a quarantine."""
