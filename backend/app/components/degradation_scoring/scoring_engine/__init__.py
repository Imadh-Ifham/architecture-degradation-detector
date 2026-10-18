"""Scoring engine subcomponent.

Author: Dahami
Date: 2026-10-14
Description:
    Normalises the criteria, derives AHP weights and ranks events with
    fixed-reference TOPSIS (LambdaMART as a comparator). Implements
    CLAUDE.md §5.5-§5.8.
"""

from app.components.degradation_scoring.scoring_engine.service import ScoringService

__all__ = ["ScoringService"]
