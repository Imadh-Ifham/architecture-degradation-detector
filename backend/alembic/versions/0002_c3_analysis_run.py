"""C3 analysis runs: run record, normalised outputs and JSON artifacts.

Revision ID: 0002_c3_analysis_run
Revises: 0001_c3_ingestion
Create Date: 2026-10-18

Mirrors app/infrastructure/postgres/models/c3_analysis_run.py; keep the two in step.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0002_c3_analysis_run"
down_revision: str | Sequence[str] | None = "0001_c3_ingestion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _run_fk(primary_key: bool = True) -> sa.Column[str]:
    return sa.Column(
        "run_id",
        sa.Text(),
        sa.ForeignKey("c3_analysis_run.run_id", ondelete="CASCADE"),
        primary_key=primary_key,
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "c3_analysis_run",
        sa.Column("run_id", sa.Text(), primary_key=True),
        sa.Column("system_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column("config_hash", sa.Text(), nullable=False),
        sa.Column("code_version", sa.Text(), nullable=False),
        sa.Column("lib_versions", JSONB(), nullable=False),
        sa.Column("releases", JSONB(), nullable=False),
        sa.Column("timings", JSONB(), nullable=False),
        sa.Column("reason_counts", JSONB(none_as_null=True)),
        sa.Column("error", sa.Text()),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'COMPLETED', 'FAILED')", name="ck_c3_analysis_run_status"
        ),
    )
    op.create_table(
        "c3_ap_instance",
        _run_fk(),
        sa.Column("release_id", sa.Text(), primary_key=True),
        sa.Column("local_instance_id", sa.Text(), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("anti_pattern_type", sa.Text(), nullable=False),
        sa.Column("catalog", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("members", JSONB(), nullable=False),
        sa.Column("measures", JSONB(), nullable=False),
    )
    op.create_table(
        "c3_trend_result",
        _run_fk(),
        sa.Column("scope", sa.Text(), primary_key=True),
        sa.Column("subject_id", sa.Text(), primary_key=True),
        sa.Column("metric", sa.Text(), primary_key=True),
        sa.Column("untested_reason", sa.Text()),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("n_points", sa.Integer(), nullable=False),
        sa.Column("unit", sa.Text()),
        sa.Column("worsening", sa.Text()),
        sa.Column("points", JSONB()),
        sa.Column("s", sa.Integer()),
        sa.Column("var_s", sa.Double()),
        sa.Column("z", sa.Double()),
        sa.Column("tau", sa.Double()),
        sa.Column("p_value", sa.Double()),
        sa.Column("q_value", sa.Double()),
        sa.Column("method", sa.Text()),
        sa.Column("time_axis", sa.Text()),
        sa.Column("sen_slope", sa.Double()),
        sa.Column("intercept", sa.Double()),
        sa.Column("is_worsening", sa.Boolean()),
        sa.Column("is_significant", sa.Boolean()),
        sa.CheckConstraint(
            "(untested_reason IS NULL) = (p_value IS NOT NULL)", name="ck_c3_trend_result_tested"
        ),
    )
    op.create_table(
        "c3_degradation_event",
        sa.Column("event_id", sa.Text(), primary_key=True),
        _run_fk(primary_key=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("event_key", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("anti_pattern_type", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.UniqueConstraint("run_id", "event_key", name="uq_c3_degradation_event_run_key"),
    )
    op.create_table(
        "c3_static_flag",
        _run_fk(),
        sa.Column("release_id", sa.Text(), primary_key=True),
        sa.Column("element_id", sa.Text(), primary_key=True),
        sa.Column("metric", sa.Text(), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("value", sa.Double(), nullable=False),
        sa.Column("threshold", sa.Double(), nullable=False),
    )
    op.create_table(
        "c3_run_artifact",
        _run_fk(),
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("payload", JSONB(), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "c3_run_artifact",
        "c3_static_flag",
        "c3_degradation_event",
        "c3_trend_result",
        "c3_ap_instance",
        "c3_analysis_run",
    ):
        op.drop_table(table)
