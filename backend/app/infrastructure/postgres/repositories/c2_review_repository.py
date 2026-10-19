"""The review queue, in Postgres.

Author: Aman Mohamed M.A
Date: 2026-10-19
Description:
    The `ReviewQueueRepository` the component writes through.

    `enqueue` is an insert that does nothing when the row is already there,
    done in one statement rather than as a check and then an insert. Two runs
    of one release can overlap, and a check that passed before an insert is
    not a guarantee - so the unique constraint does the work and the
    `ON CONFLICT DO NOTHING` makes a second arrival a no-op.

    The consequence that matters: an item somebody has already decided keeps
    its decision. A re-run must not reopen a settled question, because that
    would make a person's answer depend on how many times the pipeline
    happened to run afterwards.
"""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.components.architecture_validation.architect_review.models import (
    ReviewDecision,
    ReviewStatus,
)
from app.components.architecture_validation.models import ReviewItem, SourceTier
from app.infrastructure.postgres.models.c2_review_item import c2_review_item


class PostgresReviewQueueRepository:
    """Stores what the system would not decide alone, and what a person decided."""

    def __init__(
        self, sessions: sessionmaker[Session], repository_id: str, release_id: str
    ) -> None:
        """Bind the queue to one repository and release.

        The two ids are wiring rather than data on the item: the component is
        handed a queue that already knows which release it is for, so an item
        cannot be written against the wrong one by a caller that forgot. They
        are columns because the unique constraint needs them.
        """

        self._sessions = sessions
        self._repository_id = repository_id
        self._release_id = release_id

    def enqueue(self, item: ReviewItem) -> str:
        """Store the item if it is not already there, and return its id."""

        with self._sessions.begin() as session:
            session.execute(
                insert(c2_review_item)
                .values(**self._row(item))
                .on_conflict_do_nothing(index_elements=["item_id"])
            )
        return item.item_id

    def get(self, item_id: str) -> ReviewItem | None:
        """Return one item, or `None` when no such item exists."""

        with self._sessions() as session:
            row = session.execute(
                select(c2_review_item).where(c2_review_item.c.item_id == item_id)
            ).mappings().one_or_none()
        return _item(row) if row is not None else None

    def pending(self) -> list[ReviewItem]:
        """Return every undecided item, oldest first.

        Oldest first and not newest: a queue read newest-first buries the
        thing that has been waiting longest, which is the one item a reviewer
        most needs to see.
        """

        with self._sessions() as session:
            rows = session.execute(
                select(c2_review_item)
                .where(c2_review_item.c.status == ReviewStatus.PENDING)
                .order_by(c2_review_item.c.created_at)
            ).mappings().all()
        return [_item(row) for row in rows]

    def resolve(self, decision: ReviewDecision) -> None:
        """Record an architect's decision on one item.

        The status, who decided and when, in one update. A rejection is stored
        exactly as a confirmation is - it says a mined candidate was wrong,
        which is the only ground truth this system produces for free.
        """

        status = (
            ReviewStatus.ACCEPTED if decision.accepted else ReviewStatus.REJECTED
        )
        with self._sessions.begin() as session:
            session.execute(
                c2_review_item.update()
                .where(c2_review_item.c.item_id == decision.item_id)
                .values(
                    status=str(status),
                    decided_by=decision.decided_by,
                    decided_at=decision.decided_at,
                    note=decision.note,
                )
            )

    def _row(self, item: ReviewItem) -> dict:
        return {
            "item_id": item.item_id,
            "repository_id": self._repository_id,
            "release_id": self._release_id,
            "fact_id": item.fact_id,
            "bucket": str(item.bucket),
            "confidence": item.confidence,
            "source_tier": str(item.source_tier) if item.source_tier else None,
            "evidence_refs": list(item.evidence_refs),
            "candidate_decision_id": item.candidate_decision_id,
            "status": str(ReviewStatus.PENDING),
            "created_at": item.created_at,
        }


def _item(row) -> ReviewItem:
    """One row, as the shape the component speaks in."""

    return ReviewItem(
        item_id=row["item_id"],
        fact_id=row["fact_id"],
        bucket=row["bucket"],
        confidence=row["confidence"],
        source_tier=SourceTier(row["source_tier"]) if row["source_tier"] else None,
        evidence_refs=tuple(row["evidence_refs"]),
        candidate_decision_id=row["candidate_decision_id"],
        created_at=row["created_at"],
        status=row["status"],
    )
