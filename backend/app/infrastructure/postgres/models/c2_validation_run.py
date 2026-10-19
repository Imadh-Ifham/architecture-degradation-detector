"""C2 M8 tables: what one validation run leaves behind.

Tables carry a ``c2_`` prefix because the team shares one database and one Alembic history.
Defined with SQLAlchemy Core, like ``c3_release.py``: the repository maps rows itself, so there
is no ORM identity to manage. Created by ``alembic/versions/0004_c2_validation_run.py``; keep the
two in step.

Eight tables rather than one wide row, because what a run leaves behind is a run, its stages,
its facts and the two model outputs behind each fact - and the question this model exists to
answer is *did the two models fail on the same facts*, which needs the verdicts side by side.

``score_trace`` is ``jsonb`` and not a column per term. The terms are named by the code that
computed them, so a column each would need a migration every time a term is added - and one was
added in the week M6 was built.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Double,
    ForeignKeyConstraint,
    Index,
    Integer,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.infrastructure.postgres.database import Base

metadata = Base.metadata

_RUN_REF = ["c2_validation_run.run_id"]


c2_validation_run = Table(
    "c2_validation_run",
    metadata,
    Column("run_id", Text, primary_key=True),
    Column("repository_id", Text, nullable=False),
    Column("release_id", Text, nullable=False),
    # The ordering key, not the tag. Compared as text "v0.10.0" sorts before
    # "v0.9.0", which would place a decision's validity interval backwards.
    Column("release_sort_key", Text, nullable=False),
    # When the release happened, and which git field said so. The source is
    # stored because a suspicious ordering has to be traceable to the field
    # that produced it rather than being a mystery.
    Column("released_at", DateTime(timezone=True)),
    Column("released_at_source", Text),
    Column("c1_model_ref", Text),
    # The published document's version. A row written under 1.0.0 and one
    # written under 1.1.0 differ in which fields were even possible.
    Column("schema_version", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("generated_at", DateTime(timezone=True), nullable=False),
    Column("decision_mode", Text),
    Column("style_resolved", Text),
    Column("style_source", Text),
    # Two columns and not one: "nobody asked for this check", "this check
    # could not run" and "it ran without being shown the answer" are three
    # different statements about a run.
    Column("verification_mode", Text),
    Column("verification_arm", Text),
    Column("model_calls", Integer, nullable=False),
    Column("validation_confidence", Double, nullable=False),
    Column("reasoner_model", Text),
    Column("verifier_model", Text),
    Column("prompt_versions", JSONB, nullable=False),
    Column("published_ref", Text),
    Index(
        "ix_c2_validation_run_release",
        "repository_id",
        "release_id",
        "generated_at",
    ),
)

c2_stage_record = Table(
    "c2_stage_record",
    metadata,
    Column("run_id", Text, primary_key=True),
    Column("name", Text, primary_key=True),
    Column("status", Text, nullable=False),
    Column("counts", JSONB, nullable=False),
    Column("duration_ms", Integer, nullable=False),
    # Kept apart for the reason the dataclass keeps them apart: the note is
    # about the stage, the warnings are about the architecture, and a stage
    # that reports a warning and has it merged into a note has reported
    # nothing.
    Column("note", Text),
    Column("warnings", JSONB, nullable=False),
    ForeignKeyConstraint(["run_id"], _RUN_REF, ondelete="CASCADE"),
)

c2_classified_fact = Table(
    "c2_classified_fact",
    metadata,
    Column("run_id", Text, primary_key=True),
    Column("fact_id", Text, primary_key=True),
    Column("source_element_id", Text, nullable=False),
    Column("target_element_id", Text, nullable=False),
    Column("relationship", Text, nullable=False),
    Column("bucket", Text, nullable=False),
    Column("confidence", Double, nullable=False),
    # The arithmetic behind the number, which is the whole defence of
    # hand-set weights: it can be checked by hand from the row.
    Column("score_trace", JSONB, nullable=False),
    Column("route", Text, nullable=False),
    Column("governing_decision", Text),
    Column("source_tier", Text),
    Column("evidence_refs", JSONB, nullable=False),
    Column("model_calls", Integer, nullable=False),
    Column("produced_by", Text),
    Column("verification_outcome", Text),
    Column("arbiter_agreement", Text),
    Column("attributes", JSONB, nullable=False),
    ForeignKeyConstraint(["run_id"], _RUN_REF, ondelete="CASCADE"),
    Index("ix_c2_classified_fact_bucket", "bucket"),
)

c2_element = Table(
    "c2_element",
    metadata,
    Column("run_id", Text, primary_key=True),
    Column("element_id", Text, primary_key=True),
    # Recovery's id is stable across the releases on record, but the
    # derivation is another component's and is not a hash of the name or the
    # path - so an element's history is followed by `canonical`.
    Column("canonical", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("size", Double),
    Column("size_unit", Text),
    Column("confirmed", Integer, nullable=False),
    Column("contradicted", Integer, nullable=False),
    Column("uncovered", Integer, nullable=False),
    Column("needs_review", Integer, nullable=False),
    ForeignKeyConstraint(["run_id"], _RUN_REF, ondelete="CASCADE"),
    Index("ix_c2_element_canonical", "canonical"),
)

c2_primary_verdict = Table(
    "c2_primary_verdict",
    metadata,
    Column("run_id", Text, primary_key=True),
    Column("fact_id", Text, primary_key=True),
    Column("verdict", Text, nullable=False),
    Column("reasoning", Text, nullable=False),
    Column("cited_evidence_refs", JSONB, nullable=False),
    Column("model_id", Text, nullable=False),
    Column("prompt_version", Text, nullable=False),
    # What the model was allowed to reason from, as a hash. The package itself
    # is not stored: it is reproducible from the fact, the resolution and the
    # architecture, and storing it would copy the subject repository into the
    # database.
    Column("evidence_hash", Text, nullable=False),
    Column("cached", Boolean, nullable=False),
    Column("retried", Boolean, nullable=False),
    Column("provider", Text),
    Column("schema_mode", Text),
    Column("produced_by", Text, nullable=False),
    Column("arbiter_verdict", Text),
    Column("arbiter_basis", Text),
    Column("arbiter_agreement", Text),
    Column("guard_failures", JSONB, nullable=False),
    Column("ladder_rung", Integer, nullable=False),
    ForeignKeyConstraint(["run_id"], _RUN_REF, ondelete="CASCADE"),
)
"""The first model's answer, kept rather than summarised.

Two reasons it is a table and not a column on the fact. The sentence a
reviewer reads is the one thing in the output a model actually produced, and a
result that cannot show it is an assertion rather than evidence. And the
question the whole relational model exists to answer - *did the two models
fail on the same facts* - is a join between this table and the next one,
which is impossible if either is reduced to a verdict word.
"""

c2_verification = Table(
    "c2_verification",
    metadata,
    Column("run_id", Text, primary_key=True),
    Column("fact_id", Text, primary_key=True),
    Column("outcome", Text, nullable=False),
    Column("mechanism", Text, nullable=False),
    Column("reasoning", Text, nullable=False),
    Column("model_id", Text, nullable=False),
    Column("prompt_version", Text, nullable=False),
    # Asserted equal to the verdict's. Without it nothing says whether both
    # passes saw the same evidence, and a verification of a different package
    # is a second opinion on a different question that looks identical.
    Column("evidence_hash", Text, nullable=False),
    # The model that actually answered, not the configured one. They differ
    # exactly when it matters.
    Column("challenged_model_id", Text),
    Column("cached", Boolean, nullable=False),
    Column("retried", Boolean, nullable=False),
    Column("provider", Text),
    Column("schema_mode", Text),
    Column("guard_failures", JSONB, nullable=False),
    ForeignKeyConstraint(["run_id"], _RUN_REF, ondelete="CASCADE"),
)

c2_objection = Table(
    "c2_objection",
    metadata,
    Column("run_id", Text, primary_key=True),
    Column("fact_id", Text, primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    Column("kind", Text, nullable=False),
    # Null for the two kinds that are about the argument as a whole. A
    # reference invented for them would be worse than none.
    Column("ref", Text),
    Column("statement", Text, nullable=False),
    ForeignKeyConstraint(["run_id"], _RUN_REF, ondelete="CASCADE"),
)
"""A row per objection rather than a json array on the verification.

`AGREE` tells an architect nothing; *the cited line permits one element and
this verdict is about another* tells them where to look. Objections are the
only part of the second model's output a person can act on, and counting them
by kind across a corpus is a result about the mechanism - which a json blob
makes a parsing exercise.
"""

C2_TABLES = (
    c2_validation_run,
    c2_stage_record,
    c2_classified_fact,
    c2_element,
    c2_primary_verdict,
    c2_verification,
    c2_objection,
)
"""The seven tables M8 writes, in insertion order.

The persistence document specifies eight. `c2_decision_record` is the one
missing, and deliberately: the decision log is append-only JSONL today, the
port already allows either, and a table buys cross-repository queries nobody
has asked for. `c2_fact` folded into `c2_classified_fact` - the observed
fact's endpoints and relationship are columns there, and a separate row per
fact with nothing else on it would be a join for no reader.
"""
