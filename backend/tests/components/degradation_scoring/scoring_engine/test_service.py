"""Tests for the scoring_engine service.

Author: Dahami
Date: 2026-10-14
Description:
    Checks the package exposes exactly its service class (INSTRUCTIONS §7.3).
    Behavioural tests arrive with the task that adds the entry method.
"""

from app.components.degradation_scoring import scoring_engine
from app.components.degradation_scoring.scoring_engine.service import ScoringService


def test_package_exports_only_the_service() -> None:
    assert scoring_engine.__all__ == ["ScoringService"]
    assert scoring_engine.ScoringService is ScoringService
