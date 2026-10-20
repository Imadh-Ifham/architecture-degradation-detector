"""A repository snapshot configured for the pipeline.

Author: Imadh Ifham
Date: 2026-10-20
Description:
    What a person configures before anything is cloned: a repository url, the
    branch to read, and the release tag that names the revision. Saving one of
    these records *what to analyse*, and never starts an analysis.

    Three of these are one analysis run's input: recovery is executed for each
    in turn, and validation runs only once every one of them has recovered.

    The id is derived from the three fields rather than generated, so saving
    the same snapshot twice edits one row instead of stacking two identical
    ones - a stack with a duplicate is a stack that analyses the same revision
    twice and reports it as two releases.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime


def configuration_id_for(url: str, branch: str, release_tag: str) -> str:
    """Derive a stable id for one configured snapshot."""

    digest = hashlib.sha256(f"{url}@{branch}#{release_tag}".encode()).hexdigest()[:12]
    return f"snapshot-{digest}"


@dataclass(frozen=True)
class RepositoryConfiguration:
    """One snapshot waiting to be analysed."""

    id: str
    url: str
    branch: str
    release_tag: str
    created_at: datetime

    def to_dict(self) -> dict:
        """Serialise for the configuration file."""

        return {
            "id": self.id,
            "url": self.url,
            "branch": self.branch,
            "release_tag": self.release_tag,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict) -> "RepositoryConfiguration":
        """Rebuild a record from stored JSON.

        Raises `KeyError` or `ValueError` for a record that cannot be rebuilt;
        the store decides whether one bad row costs the whole file.
        """

        return cls(
            id=value["id"],
            url=value["url"],
            branch=value["branch"],
            release_tag=value["release_tag"],
            created_at=datetime.fromisoformat(value["created_at"]),
        )
