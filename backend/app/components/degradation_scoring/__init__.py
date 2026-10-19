"""Degradation scoring component (C4).

Author: Dahami
Date: 2026-10-14
Description:
    Consumes confirmed degradation events (C3) on the validated architecture
    graph (C2) and produces a ranked, explained severity report. Rules and
    layout: CLAUDE.md in this folder.
"""

from app.components.degradation_scoring.service import DegradationScoringService

__all__ = ["DegradationScoringService"]
