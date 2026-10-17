"""C3 M1: ingested release tables.

Revision ID: 0001_c3_ingestion
Revises:
Create Date: 2026-10-15

Mirrors app/infrastructure/postgres/models/c3_release.py; keep the two in step.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0001_c3_ingestion"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _release_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["system_id", "release_id"],
        ["c3_release.system_id", "c3_release.release_id"],
        ondelete="CASCADE",
    )


def upgrade() -> None:
    op.create_table(
        "c3_release",
        sa.Column("system_id", sa.Text(), primary_key=True),
        sa.Column("release_id", sa.Text(), primary_key=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("architecture_style", sa.Text(), nullable=False),
        sa.Column("granularity", sa.Text(), nullable=False),
        sa.Column("validation_confidence", sa.Double(), nullable=False),
        sa.Column("gate_status", sa.Text(), nullable=False),
        sa.Column("package_hash", sa.Text(), nullable=False),
        sa.Column("c1_model_ref", sa.Text()),
        sa.Column("c2_validation_ref", sa.Text()),
        sa.Column("datastore_access_supplied", sa.Boolean(), nullable=False),
        sa.Column("delegation", JSONB(none_as_null=True)),
        sa.Column("raw_json", JSONB(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "gate_status IN ('ACCEPTED', 'DOWNWEIGHTED', 'EXCLUDED')",
            name="ck_c3_release_gate_status",
        ),
    )
    op.create_table(
        "c3_element_snapshot",
        sa.Column("system_id", sa.Text(), primary_key=True),
        sa.Column("release_id", sa.Text(), primary_key=True),
        sa.Column("element_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("size", sa.Double()),
        sa.Column("size_unit", sa.Text()),
        sa.Column("aliases", JSONB(), nullable=False),
        sa.Column("layer", sa.Text()),
        sa.Column("metrics", JSONB(), nullable=False),
        sa.Column("extra", JSONB(), nullable=False),
        _release_fk(),
    )
    op.create_table(
        "c3_dependency_edge",
        sa.Column("system_id", sa.Text(), primary_key=True),
        sa.Column("release_id", sa.Text(), primary_key=True),
        sa.Column("from_id", sa.Text(), primary_key=True),
        sa.Column("to_id", sa.Text(), primary_key=True),
        sa.Column("types", JSONB(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        _release_fk(),
    )
    op.create_table(
        "c3_datastore_access",
        sa.Column("system_id", sa.Text(), primary_key=True),
        sa.Column("release_id", sa.Text(), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("element_id", sa.Text(), nullable=False),
        sa.Column("datastore", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text()),
        _release_fk(),
    )
    op.create_table(
        "c3_intent_entry",
        sa.Column("system_id", sa.Text(), primary_key=True),
        sa.Column("release_id", sa.Text(), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("intent_id", sa.Text(), nullable=False),
        sa.Column("element_id", sa.Text()),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("ref", sa.Text()),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("decision_kind", sa.Text()),
        sa.Column("date", sa.Date()),
        _release_fk(),
    )


def downgrade() -> None:
    for table in (
        "c3_intent_entry",
        "c3_datastore_access",
        "c3_dependency_edge",
        "c3_element_snapshot",
        "c3_release",
    ):
        op.drop_table(table)
