"""C3 M1 tables: ingested releases, one row set per (system_id, release_id) (plan Section 2.4).

Tables carry a ``c3_`` prefix because the team shares one database and one Alembic history.
Defined with SQLAlchemy Core: the repository maps rows to ``CanonicalRelease`` itself, so there
is no ORM identity to manage. Created by ``alembic/versions/0001_c3_ingestion.py``; keep the two
in step.
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Double,
    ForeignKeyConstraint,
    Integer,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.infrastructure.postgres.database import Base

metadata = Base.metadata

_RELEASE_KEY = ["system_id", "release_id"]
_RELEASE_REF = ["c3_release.system_id", "c3_release.release_id"]


def _release_fk() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(_RELEASE_KEY, _RELEASE_REF, ondelete="CASCADE")


c3_release = Table(
    "c3_release",
    metadata,
    Column("system_id", Text, primary_key=True),
    Column("release_id", Text, primary_key=True),
    Column("released_at", DateTime(timezone=True), nullable=False),
    Column("architecture_style", Text, nullable=False),
    Column("granularity", Text, nullable=False),
    Column("validation_confidence", Double, nullable=False),
    Column("gate_status", Text, nullable=False),
    Column("package_hash", Text, nullable=False),
    Column("c1_model_ref", Text),
    Column("c2_validation_ref", Text),
    # False: C2 did not send datastore_access (detectors that need it are skipped). True with
    # no c3_datastore_access rows: C2 sent an empty list.
    Column("datastore_access_supplied", Boolean, nullable=False),
    Column("delegation", JSONB(none_as_null=True)),  # SQL NULL = not supplied
    Column("raw_json", JSONB, nullable=False),  # the package exactly as received
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "gate_status IN ('ACCEPTED', 'DOWNWEIGHTED', 'EXCLUDED')", name="ck_c3_release_gate_status"
    ),
)

c3_element_snapshot = Table(
    "c3_element_snapshot",
    metadata,
    Column("system_id", Text, primary_key=True),
    Column("release_id", Text, primary_key=True),
    Column("element_id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("size", Double),
    Column("size_unit", Text),
    Column("aliases", JSONB, nullable=False),
    Column("layer", Text),
    Column("metrics", JSONB, nullable=False),  # JSON null inside stays null
    Column("extra", JSONB, nullable=False),
    _release_fk(),
)

c3_dependency_edge = Table(
    "c3_dependency_edge",
    metadata,
    Column("system_id", Text, primary_key=True),
    Column("release_id", Text, primary_key=True),
    Column("from_id", Text, primary_key=True),
    Column("to_id", Text, primary_key=True),
    Column("types", JSONB, nullable=False),
    Column("count", Integer, nullable=False),
    _release_fk(),
)

# C2 may list the same element/datastore pair twice; rows keep the order they arrived in.
c3_datastore_access = Table(
    "c3_datastore_access",
    metadata,
    Column("system_id", Text, primary_key=True),
    Column("release_id", Text, primary_key=True),
    Column("position", Integer, primary_key=True),
    Column("element_id", Text, nullable=False),
    Column("datastore", Text, nullable=False),
    Column("mode", Text),
    _release_fk(),
)

# Stored per release; deduplication across releases is a timeline query (M1 step 8).
c3_intent_entry = Table(
    "c3_intent_entry",
    metadata,
    Column("system_id", Text, primary_key=True),
    Column("release_id", Text, primary_key=True),
    Column("position", Integer, primary_key=True),
    Column("intent_id", Text, nullable=False),
    Column("element_id", Text),
    Column("source_type", Text, nullable=False),
    Column("ref", Text),
    Column("decision", Text, nullable=False),
    Column("decision_kind", Text),
    Column("date", Date),
    _release_fk(),
)

C3_TABLES = [
    c3_release,
    c3_element_snapshot,
    c3_dependency_edge,
    c3_datastore_access,
    c3_intent_entry,
]
