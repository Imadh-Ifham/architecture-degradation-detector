"""C4 T12: mining cache table.

Revision ID: 0002_c4_mining_cache
Revises: 0001_c3_ingestion
Create Date: 2026-10-18

Mirrors app/infrastructure/postgres/models/c4_mining_cache.py; keep the two in step.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0002_c4_mining_cache"
down_revision: str | Sequence[str] | None = "0001_c3_ingestion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "c4_mining_cache",
        sa.Column("repo_path", sa.Text(), primary_key=True),
        sa.Column("from_tag", sa.Text(), primary_key=True),
        sa.Column("to_tag", sa.Text(), primary_key=True),
        sa.Column("filter_hash", sa.Text(), primary_key=True),
        sa.Column("commit_count", sa.Integer(), nullable=False),
        sa.Column("rows", JSONB(), nullable=False),
        sa.Column("mined_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("c4_mining_cache")
