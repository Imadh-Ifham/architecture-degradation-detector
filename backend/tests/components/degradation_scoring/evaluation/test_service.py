"""Tests for the evaluation service.

Author: Dahami
Date: 2026-10-14
Description:
    Checks the package exposes exactly its service class (INSTRUCTIONS §7.3).
    Behavioural tests arrive with the task that adds the entry method.
"""

from app.components.degradation_scoring import evaluation
from app.components.degradation_scoring.evaluation.service import EvaluationService


def test_package_exports_only_the_service() -> None:
    assert evaluation.__all__ == ["EvaluationService"]
    assert evaluation.EvaluationService is EvaluationService
