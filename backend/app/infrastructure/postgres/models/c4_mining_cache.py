# C4 mining cache table: filtered commit rows per mined range (C4-T12, C4-ADR-001).
# Created by alembic/versions/0002_c4_mining_cache.py; keep the two in step.

from sqlalchemy import Column, DateTime, Integer, Table, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.infrastructure.postgres.database import Base

metadata = Base.metadata

c4_mining_cache = Table(
    "c4_mining_cache",
    metadata,
    Column("repo_path", Text, primary_key=True),
    Column("from_tag", Text, primary_key=True),
    Column("to_tag", Text, primary_key=True),
    Column("filter_hash", Text, primary_key=True),
    Column("commit_count", Integer, nullable=False),
    Column("rows", JSONB, nullable=False),
    Column("mined_at", DateTime(timezone=True), nullable=False),
)

C4_TABLES = [c4_mining_cache]
