"""C2 M7: facts held back for an architect.

Revision ID: 0005_c2_review_item
Revises: 0004_c2_validation_run
Create Date: 2026-10-19

Mirrors app/infrastructure/postgres/models/c2_review_item.py; keep the two in step.

Its own revision rather than an edit to 0004, which has already run on a shared database. A
migration that has been applied is a schema that exists in two versions the moment it is edited.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0005_c2_review_item"
down_revision: str | Sequence[str] | None = "0004_c2_validation_run"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "c2_review_item",
        sa.Column("item_id", sa.Text(), primary_key=True),
        sa.Column("repository_id", sa.Text(), nullable=False),
        sa.Column("release_id", sa.Text(), nullable=False),
        sa.Column("fact_id", sa.Text(), nullable=False),
        sa.Column("bucket", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Double(), nullable=False),
        sa.Column("source_tier", sa.Text()),
        sa.Column("evidence_refs", JSONB(), nullable=False),
        sa.Column("candidate_decision_id", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by", sa.Text()),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("note", sa.Text()),
        sa.UniqueConstraint(
            "repository_id", "release_id", "fact_id", name="uq_c2_review_item_fact"
        ),
    )
    op.create_index(
        "ix_c2_review_item_pending", "c2_review_item", ["status", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("c2_review_item")
