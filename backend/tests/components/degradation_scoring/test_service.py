"""Tests for the degradation scoring service.

Author: Dahami
Date: 2026-10-14
Description:
    Checks the component exposes exactly its orchestrating service
    (INSTRUCTIONS §7.3). Behavioural tests arrive with C4-T20.
"""

from app.components import degradation_scoring
from app.components.degradation_scoring.service import DegradationScoringService


def test_package_exports_only_the_service() -> None:
    assert degradation_scoring.__all__ == ["DegradationScoringService"]
    assert degradation_scoring.DegradationScoringService is DegradationScoringService
