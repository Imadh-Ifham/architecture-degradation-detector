"""Repository domain model.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Describes a repository that has been cloned into the local ingestion
    workspace, plus the small serialisation contract used by its metadata file.

    Two identities are recorded, and they are not the same thing:

      * `id`            - the workspace directory this particular clone occupies.
                          A release-aware clone is keyed by its revision, so two
                          releases of one repository have two ids.
      * `repository_id` - the repository itself, independent of any release.
                          This is what architecture snapshots are stored under.

    `repository_id` is optional so metadata written before release-aware
    ingestion still loads; it then falls back to `id`.
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
    repository_id: str | None = None
    release_tag: str | None = None
    revision: str | None = None
    release_date: datetime | None = None
    release_date_source: str | None = None
    commit_date: datetime | None = None

    @property
    def repository_key(self) -> str:
        """The repository's stable identity, independent of the revision."""

        return self.repository_id or self.id

    @property
    def release_id(self) -> str:
        """The readable name of the analyzed revision."""

        return self.release_tag or f"commit:{self.commit[:12]}"

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
            "repository_id": self.repository_key,
            "release_tag": self.release_tag,
            "revision": self.revision,
            "release_date": (
                self.release_date.isoformat() if self.release_date else None
            ),
            "release_date_source": self.release_date_source,
            "commit_date": (
                self.commit_date.isoformat() if self.commit_date else None
            ),
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
            repository_id=metadata.get("repository_id") or metadata["id"],
            release_tag=metadata.get("release_tag"),
            revision=metadata.get("revision"),
            release_date=_parse(metadata.get("release_date")),
            release_date_source=metadata.get("release_date_source"),
            commit_date=_parse(metadata.get("commit_date")),
        )


def _parse(value: str | None) -> datetime | None:
    """Read an ISO 8601 timestamp, or nothing at all."""

    return datetime.fromisoformat(value) if value else None
