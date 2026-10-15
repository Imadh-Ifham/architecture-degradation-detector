"""Repository ingestion subcomponent.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Clones a repository at a given branch into a local workspace and removes
    it again. Re-exports the public surface of the subcomponent.
"""

from app.components.architecture_recovery.repository_ingestion.errors import (
    InvalidRepositorySource,
    RepositoryIngestionError,
    RepositoryNotFound,
)
from app.components.architecture_recovery.repository_ingestion.service import (
    RepositoryIngestionService,
)

__all__ = [
    "InvalidRepositorySource",
    "RepositoryIngestionError",
    "RepositoryIngestionService",
    "RepositoryNotFound",
]
