"""AuditEntryV1: one architect verdict in the append-only audit trail (plan Section 3.3).

Declared now so the contract and its schema are stable; written by M7 after PP1. The minimum
note length is configuration (``review.note_min_chars``) and is enforced by M7, not here.
"""

from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from app.domain.boundary import BoundaryModel, NonEmptyStr, Sha256


class Verdict(StrEnum):
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    NEEDS_INVESTIGATION = "NEEDS_INVESTIGATION"


NOTE_REQUIRED_FOR = frozenset({Verdict.REJECTED, Verdict.NEEDS_INVESTIGATION})


class AuditEntryV1(BoundaryModel):
    model_config = ConfigDict(title="AuditEntryV1")

    audit_id: NonEmptyStr
    seq: int = Field(ge=1)
    event_id: NonEmptyStr
    event_key: Sha256
    verdict: Verdict
    reviewer_id: NonEmptyStr
    note: str | None = None
    timestamp: AwareDatetime
    evidence_snapshot_ref: Sha256
    prev_hash: Sha256 | None = None
    entry_hash: Sha256

    @model_validator(mode="after")
    def _check_note_given_with_disagreement(self) -> Self:
        if self.verdict in NOTE_REQUIRED_FOR and not (self.note or "").strip():
            raise ValueError(f"note is required for verdict {self.verdict.value}")
        return self
