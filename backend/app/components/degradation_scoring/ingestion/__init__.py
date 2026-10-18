"""Ingestion subcomponent.

Author: Dahami
Date: 2026-10-14
Description:
    Validates C3 degradation events and quarantines malformed, non-confirmed
    and intentional ones; resolves event elements to graph nodes; parses ADR
    index entries. Implements CLAUDE.md §4.1, §5.1 (resolution) and §5.3
    (ADR loading).
"""

from app.components.degradation_scoring.ingestion.service import IngestionService

__all__ = ["IngestionService"]
