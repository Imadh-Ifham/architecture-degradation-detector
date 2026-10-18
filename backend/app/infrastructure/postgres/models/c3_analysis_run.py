"""C3 analysis-run tables: one row set per ``run_id`` (plan Section 2.4, T-13).

What the report and the evaluation read is normalised (instances, tested and untested series,
events, static flags); the intermediate artifacts (observations, lineages, tracks, series) are
one JSONB row each in ``c3_run_artifact``. Every child row cascades from its run.

Defined with SQLAlchemy Core, like ``c3_release.py``. Created by
``alembic/versions/0002_c3_analysis_run.py``; keep the two in step.
"""

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
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.infrastructure.postgres.database import Base

metadata = Base.metadata


def _run_fk() -> Column[str]:
    return Column(
        "run_id",
        Text,
        ForeignKey("c3_analysis_run.run_id", ondelete="CASCADE"),
        primary_key=True,
    )


c3_analysis_run = Table(
    "c3_analysis_run",
    metadata,
    Column("run_id", Text, primary_key=True),
    Column("system_id", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("config", JSONB, nullable=False),
    Column("config_hash", Text, nullable=False),
    Column("code_version", Text, nullable=False),
    Column("lib_versions", JSONB, nullable=False),
    Column("releases", JSONB, nullable=False),  # the timeline, in order
    Column("timings", JSONB, nullable=False),
    Column("reason_counts", JSONB(none_as_null=True)),  # SQL NULL = not counted
    Column("error", Text),
    CheckConstraint(
        "status IN ('RUNNING', 'COMPLETED', 'FAILED')", name="ck_c3_analysis_run_status"
    ),
)

c3_ap_instance = Table(
    "c3_ap_instance",
    metadata,
    _run_fk(),
    Column("release_id", Text, primary_key=True),
    Column("local_instance_id", Text, primary_key=True),
    Column("position", Integer, nullable=False),  # output order
    Column("anti_pattern_type", Text, nullable=False),
    Column("catalog", Text, nullable=False),
    Column("scope", Text, nullable=False),
    Column("members", JSONB, nullable=False),
    Column("measures", JSONB, nullable=False),  # JSON null inside stays null
)

# Tested and untested series in one table: ``untested_reason`` is null exactly when the
# statistics are set.
c3_trend_result = Table(
    "c3_trend_result",
    metadata,
    _run_fk(),
    Column("scope", Text, primary_key=True),
    Column("subject_id", Text, primary_key=True),
    Column("metric", Text, primary_key=True),
    Column("untested_reason", Text),
    Column("position", Integer, nullable=False),  # order among the tested, or the untested
    Column("n_points", Integer, nullable=False),  # non-null points
    Column("unit", Text),
    Column("worsening", Text),
    Column("points", JSONB),
    Column("s", Integer),
    Column("var_s", Double),
    Column("z", Double),
    Column("tau", Double),
    Column("p_value", Double),
    Column("q_value", Double),
    Column("method", Text),
    Column("time_axis", Text),
    Column("sen_slope", Double),
    Column("intercept", Double),
    Column("is_worsening", Boolean),
    Column("is_significant", Boolean),
    CheckConstraint(
        "(untested_reason IS NULL) = (p_value IS NOT NULL)", name="ck_c3_trend_result_tested"
    ),
)

c3_degradation_event = Table(
    "c3_degradation_event",
    metadata,
    Column("event_id", Text, primary_key=True),
    Column(
        "run_id",
        Text,
        ForeignKey("c3_analysis_run.run_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("position", Integer, nullable=False),  # export order
    Column("event_key", Text, nullable=False),
    Column("scope", Text, nullable=False),
    Column("anti_pattern_type", Text, nullable=False),
    Column("payload", JSONB, nullable=False),  # the DegradationEventV2 as exported
    UniqueConstraint("run_id", "event_key", name="uq_c3_degradation_event_run_key"),
)

c3_static_flag = Table(
    "c3_static_flag",
    metadata,
    _run_fk(),
    Column("release_id", Text, primary_key=True),
    Column("element_id", Text, primary_key=True),
    Column("metric", Text, primary_key=True),
    Column("position", Integer, nullable=False),  # output order
    Column("value", Double, nullable=False),
    Column("threshold", Double, nullable=False),
)

c3_run_artifact = Table(
    "c3_run_artifact",
    metadata,
    _run_fk(),
    Column("name", Text, primary_key=True),
    Column("payload", JSONB, nullable=False),
)

C3_RUN_TABLES = [
    c3_analysis_run,
    c3_ap_instance,
    c3_trend_result,
    c3_degradation_event,
    c3_static_flag,
    c3_run_artifact,
]
