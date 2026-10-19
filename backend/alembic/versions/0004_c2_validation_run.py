"""C2 M8: what one validation run leaves behind.

Revision ID: 0004_c2_validation_run
Revises: 0003_c4_scoring_run
Create Date: 2026-10-19

Mirrors app/infrastructure/postgres/models/c2_validation_run.py; keep the two in step.

Additive and `c2_`-prefixed throughout. No existing table is altered and no earlier revision is
edited: a migration that has already run on somebody's database is a schema that exists in two
versions.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0004_c2_validation_run"
down_revision: str | Sequence[str] | None = "0003_c4_scoring_run"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "c2_objection",
    "c2_verification",
    "c2_primary_verdict",
    "c2_element",
    "c2_classified_fact",
    "c2_stage_record",
    "c2_validation_run",
)
"""Dropped in this order, children first, because every one of them cascades
from the run."""


def _run_fk() -> sa.Column[str]:
    return sa.Column(
        "run_id",
        sa.Text(),
        sa.ForeignKey("c2_validation_run.run_id", ondelete="CASCADE"),
        primary_key=True,
    )


def upgrade() -> None:
    op.create_table(
        "c2_validation_run",
        sa.Column("run_id", sa.Text(), primary_key=True),
        sa.Column("repository_id", sa.Text(), nullable=False),
        sa.Column("release_id", sa.Text(), nullable=False),
        sa.Column("release_sort_key", sa.Text(), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("released_at_source", sa.Text()),
        sa.Column("c1_model_ref", sa.Text()),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_mode", sa.Text()),
        sa.Column("style_resolved", sa.Text()),
        sa.Column("style_source", sa.Text()),
        sa.Column("verification_mode", sa.Text()),
        sa.Column("verification_arm", sa.Text()),
        sa.Column("model_calls", sa.Integer(), nullable=False),
        sa.Column("validation_confidence", sa.Double(), nullable=False),
        sa.Column("reasoner_model", sa.Text()),
        sa.Column("verifier_model", sa.Text()),
        sa.Column("prompt_versions", JSONB(), nullable=False),
        sa.Column("published_ref", sa.Text()),
    )
    op.create_index(
        "ix_c2_validation_run_release",
        "c2_validation_run",
        ["repository_id", "release_id", "generated_at"],
    )

    op.create_table(
        "c2_stage_record",
        _run_fk(),
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("counts", JSONB(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("warnings", JSONB(), nullable=False),
    )

    op.create_table(
        "c2_classified_fact",
        _run_fk(),
        sa.Column("fact_id", sa.Text(), primary_key=True),
        sa.Column("source_element_id", sa.Text(), nullable=False),
        sa.Column("target_element_id", sa.Text(), nullable=False),
        sa.Column("relationship", sa.Text(), nullable=False),
        sa.Column("bucket", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Double(), nullable=False),
        sa.Column("score_trace", JSONB(), nullable=False),
        sa.Column("route", sa.Text(), nullable=False),
        sa.Column("governing_decision", sa.Text()),
        sa.Column("source_tier", sa.Text()),
        sa.Column("evidence_refs", JSONB(), nullable=False),
        sa.Column("model_calls", sa.Integer(), nullable=False),
        sa.Column("produced_by", sa.Text()),
        sa.Column("verification_outcome", sa.Text()),
        sa.Column("arbiter_agreement", sa.Text()),
        sa.Column("attributes", JSONB(), nullable=False),
    )
    op.create_index("ix_c2_classified_fact_bucket", "c2_classified_fact", ["bucket"])

    op.create_table(
        "c2_element",
        _run_fk(),
        sa.Column("element_id", sa.Text(), primary_key=True),
        sa.Column("canonical", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("size", sa.Double()),
        sa.Column("size_unit", sa.Text()),
        sa.Column("confirmed", sa.Integer(), nullable=False),
        sa.Column("contradicted", sa.Integer(), nullable=False),
        sa.Column("uncovered", sa.Integer(), nullable=False),
        sa.Column("needs_review", sa.Integer(), nullable=False),
    )
    op.create_index("ix_c2_element_canonical", "c2_element", ["canonical"])

    op.create_table(
        "c2_primary_verdict",
        _run_fk(),
        sa.Column("fact_id", sa.Text(), primary_key=True),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("cited_evidence_refs", JSONB(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("evidence_hash", sa.Text(), nullable=False),
        sa.Column("cached", sa.Boolean(), nullable=False),
        sa.Column("retried", sa.Boolean(), nullable=False),
        sa.Column("provider", sa.Text()),
        sa.Column("schema_mode", sa.Text()),
        sa.Column("produced_by", sa.Text(), nullable=False),
        sa.Column("arbiter_verdict", sa.Text()),
        sa.Column("arbiter_basis", sa.Text()),
        sa.Column("arbiter_agreement", sa.Text()),
        sa.Column("guard_failures", JSONB(), nullable=False),
        sa.Column("ladder_rung", sa.Integer(), nullable=False),
    )

    op.create_table(
        "c2_verification",
        _run_fk(),
        sa.Column("fact_id", sa.Text(), primary_key=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("mechanism", sa.Text(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("evidence_hash", sa.Text(), nullable=False),
        sa.Column("challenged_model_id", sa.Text()),
        sa.Column("cached", sa.Boolean(), nullable=False),
        sa.Column("retried", sa.Boolean(), nullable=False),
        sa.Column("provider", sa.Text()),
        sa.Column("schema_mode", sa.Text()),
        sa.Column("guard_failures", JSONB(), nullable=False),
    )

    op.create_table(
        "c2_objection",
        _run_fk(),
        sa.Column("fact_id", sa.Text(), primary_key=True),
        sa.Column("ordinal", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("ref", sa.Text()),
        sa.Column("statement", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    for table in TABLES:
        op.drop_table(table)
