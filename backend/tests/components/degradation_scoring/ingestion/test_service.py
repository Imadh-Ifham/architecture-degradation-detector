"""Tests for the ingestion service.

Author: Dahami
Date: 2026-10-14
Description:
    Checks the package exposes exactly its service class (INSTRUCTIONS §7.3).
    Behavioural tests arrive with the task that adds the entry method.
"""

from app.components.degradation_scoring import ingestion
from app.components.degradation_scoring.ingestion.service import IngestionService


def test_package_exports_only_the_service() -> None:
    assert ingestion.__all__ == ["IngestionService"]
    assert ingestion.IngestionService is IngestionService
