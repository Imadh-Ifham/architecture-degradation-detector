# C4 run record for inspection : one run, what happened to each input
# payload (layer 1), each ranked event's raw features (layer 2). One plain column per value;
# layer 3 adds c4_event_scores keyed by (run_id, event_id). Created by
# alembic/versions/0003_c4_scoring_run.py; keep the two in step.

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from app.infrastructure.postgres.database import Base

metadata = Base.metadata


def _run_fk() -> Column[str]:
    return Column(
        "run_id",
        Text,
        ForeignKey("c4_scoring_run.run_id", ondelete="CASCADE"),
        primary_key=True,
    )


c4_scoring_run = Table(
    "c4_scoring_run",
    metadata,
    Column("run_id", Text, primary_key=True),
    Column("system_id", Text, nullable=False),
    Column("release_id", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("data_provenance", Text, nullable=False),
    Column("code_commit", Text),
    Column("payloads", Integer, nullable=False),
    Column("ranked", Integer, nullable=False),
    Column("skipped", Integer, nullable=False),
    Column("quarantined", Integer, nullable=False),
    Column("resolution_rate", Double, nullable=False),
    Column("hotspot_active", Boolean, nullable=False),
    Column("hotspot_inactive_reason", Text),
    Column("half_life_days", Double),
    Column("decay_rate_per_day", Double),
    Column("cochange_threshold", Integer, nullable=False),
    Column("max_files_per_commit", Integer, nullable=False),
    Column("unmapped_line_share", Double),
    Column("adr_active", Boolean, nullable=False),
    Column("adr_inactive_reason", Text),
    Column("details", JSONB, nullable=False),  # small extras: ADR weight table, repo path
)

c4_event_ingestion = Table(
    "c4_event_ingestion",
    metadata,
    _run_fk(),
    Column("payload_index", Integer, primary_key=True),
    Column("event_id", Text),  # None for a malformed payload without an id
    Column("scope", Text),
    Column("anti_pattern_type", Text),
    Column("review_status", Text),
    Column("context_tag", Text),
    Column("outcome", Text, nullable=False),
    Column("reason", Text),
    Column("detail", Text),
    Column("nodes", ARRAY(Text), nullable=False),
    Column("resolution_status", Text),
    Column("resolution_confidence", Double),
    CheckConstraint(
        "outcome IN ('ranked', 'skipped', 'quarantined')", name="ck_c4_event_ingestion_outcome"
    ),
)

c4_event_features = Table(
    "c4_event_features",
    metadata,
    _run_fk(),
    Column("event_id", Text, primary_key=True),
    # blast radius (always)
    Column("br_fan_in_ratio", Double, nullable=False),
    Column("br_pagerank", Double, nullable=False),
    Column("br_betweenness", Double, nullable=False),
    Column("br_depth", Integer, nullable=False),
    Column("br_betweenness_sampled", Boolean, nullable=False),
    # evolutionary hotspot (NULL when hotspot is off for the run)
    Column("eh_churn_decayed", Double),
    Column("eh_authors", Integer),
    Column("eh_coupling", Integer),
    Column("eh_bugfix_ratio", Double),
    Column("eh_commits", Integer),
    Column("eh_from_release", Text),
    Column("eh_to_release", Text),
    Column("eh_first_seen_fallback", Boolean),
    Column("eh_paths_available", Boolean),
    # persistence (always)
    Column("ps_consecutive_releases", Integer, nullable=False),
    Column("ps_growth_slope", Double, nullable=False),
    Column("ps_growth_slope_available", Boolean, nullable=False),
    Column("ps_growth_metric", Text),
    Column("ps_presence_fallback", Boolean, nullable=False),
    # ADR violation (NULL when AV is off for the run)
    Column("av_weight", Double),
    Column("av_adr_id", Text),
    Column("av_linked_adrs", ARRAY(Text)),
)

C4_RUN_TABLES = [c4_scoring_run, c4_event_ingestion, c4_event_features]
