"""Tests for the reporting service.

Author: Dahami
Date: 2026-10-14
Description:
    Checks the package exposes exactly its service class (INSTRUCTIONS §7.3).
    Behavioural tests arrive with the task that adds the entry method.
"""

from app.components.degradation_scoring import reporting
from app.components.degradation_scoring.reporting.service import ReportingService


def test_package_exports_only_the_service() -> None:
    assert reporting.__all__ == ["ReportingService"]
    assert reporting.ReportingService is ReportingService
