"""Tests for the features service.

Author: Dahami
Date: 2026-10-14
Description:
    Checks the package exposes exactly its service class (INSTRUCTIONS §7.3).
    Behavioural tests arrive with the task that adds the entry method.
"""

from app.components.degradation_scoring import features
from app.components.degradation_scoring.features.service import FeatureExtractionService


def test_package_exports_only_the_service() -> None:
    assert features.__all__ == ["FeatureExtractionService"]
    assert features.FeatureExtractionService is FeatureExtractionService
