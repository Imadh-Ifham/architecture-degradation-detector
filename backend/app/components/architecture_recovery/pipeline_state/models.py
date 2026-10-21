"""How far one configured snapshot has got on this machine.

Author: Imadh Ifham
Date: 2026-10-21
Description:
    The pipeline's question is not "what does this snapshot contain" but "what
    is left to do". Answering it needs two facts about the machine and none
    about the architecture: whether the revision is cloned, and whether a
    recovery that finished left an architecture behind.

    **State is read from what a run wrote, never from a name.** A clone is a
    metadata record beside a working tree; a recovery is a run record that
    finished graph construction *and* the snapshot it produced. A directory
    that happens to be there proves nothing, and calling it recovered would
    skip exactly the work that had failed.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class SnapshotStage(str, Enum):
    """What a configured snapshot already has."""

    PENDING = "pending"
    """Nothing on disk: the snapshot would still be cloned."""

    CLONED = "cloned"
    """The revision is checked out and has never been recovered."""

    RECOVERED = "recovered"
    """A completed recovery left an architecture for this checkout."""


@dataclass(frozen=True)
class CloneState:
    """What the checkout on disk says about itself."""

    id: str
    commit: str
    branch: str
    release_tag: str | None
    ingested_at: datetime

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "commit": self.commit,
            "branch": self.branch,
            "release_tag": self.release_tag,
            "ingested_at": self.ingested_at.isoformat(),
        }


@dataclass(frozen=True)
class RecoveryState:
    """What the last completed recovery of this checkout produced.

    The counts come from the run record rather than from the snapshot, so the
    answer costs one small file instead of a parse of the graph itself.
    """

    release_id: str
    commit_sha: str
    finished_at: str | None
    duration_ms: int | None
    element_count: int | None
    relationship_count: int | None

    def to_dict(self) -> dict:
        return {
            "release_id": self.release_id,
            "commit_sha": self.commit_sha,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "element_count": self.element_count,
            "relationship_count": self.relationship_count,
        }


@dataclass(frozen=True)
class SnapshotState:
    """One configured snapshot, and what running the pipeline would still do."""

    configuration_id: str
    url: str
    branch: str
    release_tag: str
    workspace_id: str
    stage: SnapshotStage
    clone: CloneState | None = None
    recovery: RecoveryState | None = None

    @property
    def needs_clone(self) -> bool:
        """Whether the pipeline would have to clone this snapshot."""

        return self.clone is None

    @property
    def needs_recovery(self) -> bool:
        """Whether the pipeline would have to recover it."""

        return self.recovery is None

    def to_dict(self) -> dict:
        return {
            "configuration_id": self.configuration_id,
            "url": self.url,
            "branch": self.branch,
            "release_tag": self.release_tag,
            "workspace_id": self.workspace_id,
            "stage": self.stage.value,
            "needs_clone": self.needs_clone,
            "needs_recovery": self.needs_recovery,
            "clone": self.clone.to_dict() if self.clone else None,
            "recovery": self.recovery.to_dict() if self.recovery else None,
        }


__all__ = [
    "CloneState",
    "RecoveryState",
    "SnapshotStage",
    "SnapshotState",
]
