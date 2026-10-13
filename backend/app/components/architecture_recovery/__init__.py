"""Architecture recovery component.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Reconstructs the architecture of a system as it actually is (the as-is
    model used by every later research stage). Currently exposes the
    repository ingestion subcomponent.
"""

from app.components.architecture_recovery.repository_ingestion.service import (
    RepositoryIngestionService,
)

__all__ = ["RepositoryIngestionService"]
