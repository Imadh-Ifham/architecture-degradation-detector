"""C4 T19: per-event scores (layer 3) for the run record.

Revision ID: 0004_c4_event_scores
Revises: 0003_c4_scoring_run
Create Date: 2026-10-18

Mirrors c4_event_scores in app/infrastructure/postgres/models/c4_scoring_run.py; keep the two
in step.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_c4_event_scores"
down_revision: str | Sequence[str] | None = "0003_c4_scoring_run"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _criterion_columns(prefix: str) -> list[sa.Column[float]]:
    return [
        sa.Column(f"{prefix}_normalized", sa.Double()),
        sa.Column(f"{prefix}_weight", sa.Double(), nullable=False),
        sa.Column(f"{prefix}_contribution", sa.Double(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "c4_event_scores",
        sa.Column("run_id", sa.Text(), primary_key=True),
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("severity", sa.Double(), nullable=False),
        sa.Column("distance_ideal", sa.Double(), nullable=False),
        sa.Column("distance_anti_ideal", sa.Double(), nullable=False),
        *_criterion_columns("br"),
        *_criterion_columns("eh"),
        *_criterion_columns("av"),
        *_criterion_columns("ps"),
        sa.ForeignKeyConstraint(
            ["run_id", "event_id"],
            ["c4_event_features.run_id", "c4_event_features.event_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("rank >= 1", name="ck_c4_event_scores_rank"),
        sa.CheckConstraint("severity BETWEEN 0 AND 1", name="ck_c4_event_scores_severity"),
    )


def downgrade() -> None:
    op.drop_table("c4_event_scores")
