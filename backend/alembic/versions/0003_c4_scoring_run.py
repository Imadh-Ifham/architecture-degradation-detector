"""C4 T16b: run record tables for inspection.

Revision ID: 0003_c4_scoring_run
Revises: 0002_c4_mining_cache
Create Date: 2026-10-18

Mirrors app/infrastructure/postgres/models/c4_scoring_run.py; keep the two in step.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from alembic import op

revision: str = "0003_c4_scoring_run"
down_revision: str | Sequence[str] | None = "0002_c4_mining_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _run_fk() -> sa.Column[str]:
    return sa.Column(
        "run_id",
        sa.Text(),
        sa.ForeignKey("c4_scoring_run.run_id", ondelete="CASCADE"),
        primary_key=True,
    )


def upgrade() -> None:
    op.create_table(
        "c4_scoring_run",
        sa.Column("run_id", sa.Text(), primary_key=True),
        sa.Column("system_id", sa.Text(), nullable=False),
        sa.Column("release_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_provenance", sa.Text(), nullable=False),
        sa.Column("code_commit", sa.Text()),
        sa.Column("payloads", sa.Integer(), nullable=False),
        sa.Column("ranked", sa.Integer(), nullable=False),
        sa.Column("skipped", sa.Integer(), nullable=False),
        sa.Column("quarantined", sa.Integer(), nullable=False),
        sa.Column("resolution_rate", sa.Double(), nullable=False),
        sa.Column("hotspot_active", sa.Boolean(), nullable=False),
        sa.Column("hotspot_inactive_reason", sa.Text()),
        sa.Column("half_life_days", sa.Double()),
        sa.Column("decay_rate_per_day", sa.Double()),
        sa.Column("cochange_threshold", sa.Integer(), nullable=False),
        sa.Column("max_files_per_commit", sa.Integer(), nullable=False),
        sa.Column("unmapped_line_share", sa.Double()),
        sa.Column("adr_active", sa.Boolean(), nullable=False),
        sa.Column("adr_inactive_reason", sa.Text()),
        sa.Column("details", JSONB(), nullable=False),
    )
    op.create_table(
        "c4_event_ingestion",
        _run_fk(),
        sa.Column("payload_index", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Text()),
        sa.Column("scope", sa.Text()),
        sa.Column("anti_pattern_type", sa.Text()),
        sa.Column("review_status", sa.Text()),
        sa.Column("context_tag", sa.Text()),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("detail", sa.Text()),
        sa.Column("nodes", ARRAY(sa.Text()), nullable=False),
        sa.Column("resolution_status", sa.Text()),
        sa.Column("resolution_confidence", sa.Double()),
        sa.CheckConstraint(
            "outcome IN ('ranked', 'skipped', 'quarantined')",
            name="ck_c4_event_ingestion_outcome",
        ),
    )
    op.create_table(
        "c4_event_features",
        _run_fk(),
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("br_fan_in_ratio", sa.Double(), nullable=False),
        sa.Column("br_pagerank", sa.Double(), nullable=False),
        sa.Column("br_betweenness", sa.Double(), nullable=False),
        sa.Column("br_depth", sa.Integer(), nullable=False),
        sa.Column("br_betweenness_sampled", sa.Boolean(), nullable=False),
        sa.Column("eh_churn_decayed", sa.Double()),
        sa.Column("eh_authors", sa.Integer()),
        sa.Column("eh_coupling", sa.Integer()),
        sa.Column("eh_bugfix_ratio", sa.Double()),
        sa.Column("eh_commits", sa.Integer()),
        sa.Column("eh_from_release", sa.Text()),
        sa.Column("eh_to_release", sa.Text()),
        sa.Column("eh_first_seen_fallback", sa.Boolean()),
        sa.Column("eh_paths_available", sa.Boolean()),
        sa.Column("ps_consecutive_releases", sa.Integer(), nullable=False),
        sa.Column("ps_growth_slope", sa.Double(), nullable=False),
        sa.Column("ps_growth_slope_available", sa.Boolean(), nullable=False),
        sa.Column("ps_growth_metric", sa.Text()),
        sa.Column("ps_presence_fallback", sa.Boolean(), nullable=False),
        sa.Column("av_weight", sa.Double()),
        sa.Column("av_adr_id", sa.Text()),
        sa.Column("av_linked_adrs", ARRAY(sa.Text())),
    )


def downgrade() -> None:
    for table in ("c4_event_features", "c4_event_ingestion", "c4_scoring_run"):
        op.drop_table(table)
