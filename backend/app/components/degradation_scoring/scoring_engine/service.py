"""Scoring engine service.

Author: Dahami
Date: 2026-10-14
Description:
    Normalises the criteria, derives AHP weights and ranks events with
    fixed-reference TOPSIS (LambdaMART as a comparator). Implements
    CLAUDE.md §5.5-§5.8.

    Scaffold only (C4-T02): the public entry method is added by C4-T17.
"""


class ScoringService:
    """Ranks events by severity from their criteria values."""
