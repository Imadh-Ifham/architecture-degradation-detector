"""Repository inventory HTTP schemas.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Response bodies describing an inventory produced for an ingested
    repository. Kept separate from the ingestion schemas so that neither
    subcomponent has to import the other; the API layer composes the two.
"""

from pathlib import Path

from pydantic import BaseModel

from app.components.architecture_recovery.repository_inventory.models import (
    RepositoryInventory,
)


class RepositoryInventorySummaryResponse(BaseModel):
    """Where an inventory was written and what it contains."""

    path: str
    file_count: int
    component_count: int
    relationship_count: int
    truncated: bool
    warning_count: int
    by_category: dict[str, int]
    by_language: dict[str, int]

    @classmethod
    def from_inventory(
        cls, path: Path, inventory: RepositoryInventory
    ) -> "RepositoryInventorySummaryResponse":
        """Build the response from a completed inventory and its output path."""

        summary = inventory.summary

        return cls(
            path=str(path),
            file_count=summary.file_count,
            component_count=summary.component_count,
            relationship_count=summary.relationship_count,
            truncated=summary.truncated,
            warning_count=len(inventory.warnings),
            by_category=summary.by_category,
            by_language=summary.by_language,
        )
