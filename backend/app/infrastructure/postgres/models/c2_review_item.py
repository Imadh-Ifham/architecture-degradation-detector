"""C2 M7 table: facts held back for an architect.

Tables carry a ``c2_`` prefix because the team shares one database and one Alembic history.
Created by ``alembic/versions/0005_c2_review_item.py``; keep the two in step.

One table, three statuses, and no workflow. No claiming, no reassignment, no due date, no
priority: one list, one drill-in, one decision. A fourth status column here would be the first
step of a process this component has no business running.

The row holds **references and state**, never copies. The evidence and the candidate decision
live in the knowledge log and the published document, and a second copy here would be the one
that goes stale with no way to tell which was right.
"""

from sqlalchemy import (
    Column,
    DateTime,
    Double,
    Index,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.infrastructure.postgres.database import Base

metadata = Base.metadata

c2_review_item = Table(
    "c2_review_item",
    metadata,
    # Content-addressed from (repository_id, release_id, fact_id), so a re-run
    # of a release produces the identical id and the insert is a no-op. A
    # generated id would make the second run's row a new row, and the unique
    # constraint would then be rejecting rows the component thought differed.
    Column("item_id", Text, primary_key=True),
    Column("repository_id", Text, nullable=False),
    Column("release_id", Text, nullable=False),
    Column("fact_id", Text, nullable=False),
    Column("bucket", Text, nullable=False),
    Column("confidence", Double, nullable=False),
    # For the architect rather than for the system: it is what lets the screen
    # say *why* this needs a person instead of showing a number below a
    # threshold and leaving them to guess.
    Column("source_tier", Text),
    Column("evidence_refs", JSONB, nullable=False),
    Column("candidate_decision_id", Text),
    Column("status", Text, nullable=False),  # pending | accepted | rejected
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("decided_by", Text),
    Column("decided_at", DateTime(timezone=True)),
    Column("note", Text),
    # The whole of the idempotency rule, as a constraint rather than a
    # check-then-insert: two runs of one release can overlap, and a check that
    # passed before an insert is not a guarantee.
    UniqueConstraint(
        "repository_id", "release_id", "fact_id", name="uq_c2_review_item_fact"
    ),
    Index("ix_c2_review_item_pending", "status", "created_at"),
)

C2_REVIEW_TABLES = (c2_review_item,)
"""One table, and it is deliberately the whole of this unit's schema."""
