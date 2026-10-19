"""Tests for the explanation service.

Author: Dahami
Date: 2026-10-14
Description:
    Checks the package exposes exactly its service class (INSTRUCTIONS §7.3).
    Behavioural tests arrive with the task that adds the entry method.
"""

from app.components.degradation_scoring import explanation
from app.components.degradation_scoring.explanation.service import ExplanationService


def test_package_exports_only_the_service() -> None:
    assert explanation.__all__ == ["ExplanationService"]
    assert explanation.ExplanationService is ExplanationService
