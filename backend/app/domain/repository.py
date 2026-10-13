"""Repository domain model.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Describes a repository that has been cloned into the local ingestion
    workspace, plus the small serialisation contract used by its metadata file.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class IngestedRepository:
    """A repository that has been cloned into the local workspace."""

    id: str
    url: str
    branch: str
    commit: str
    path: Path
    ingested_at: datetime

    def to_metadata(self) -> dict:
        """Serialise the record for storage in the workspace `metadata.json`.

        `path` is deliberately omitted: it is derived from the workspace root
        and the id, so it must not be persisted.
        """

        return {
            "id": self.id,
            "url": self.url,
            "branch": self.branch,
            "commit": self.commit,
            "ingested_at": self.ingested_at.isoformat(),
        }

    @classmethod
    def from_metadata(cls, metadata: dict, path: Path) -> "IngestedRepository":
        """Rebuild a record from its stored metadata and resolved path."""

        return cls(
            id=metadata["id"],
            url=metadata["url"],
            branch=metadata["branch"],
            commit=metadata["commit"],
            path=path,
            ingested_at=datetime.fromisoformat(metadata["ingested_at"]),
        )
