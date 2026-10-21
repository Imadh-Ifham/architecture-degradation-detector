"""PostgresRunRepository against a real database (Docker: ``docker compose up -d``).

Every test runs inside one outer transaction that is rolled back, tables included, so the
development database is left as it was. Skips when PostgreSQL is not reachable - which is the
normal state on a laptop, and the reason the component treats a failed record as a warning
rather than a failed run.

The question this file exists to protect is the one the relational model exists for: *did the two
models fail on the same facts*. It is a join between the verdict table and the verification
table, and it is only answerable because both are stored in full rather than reduced to a word.
"""

import datetime as dt
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.components.architecture_validation.models import (
    ArbiterAgreement,
    ClassifiedFact,
    Objection,
    ObjectionKind,
    PrimaryVerdict,
    ScoreTrace,
    SourceTier,
    StageRecord,
    StageStatus,
    ValidationRunResult,
    Verdict,
    Verification,
    VerificationOutcome,
)
from app.domain.validated_architecture import (
    RunMode,
    ValidatedArchitectureGraph,
    ValidatedNode,
    ValidationRollup,
    ValidationRunStamp,
)

pytestmark = pytest.mark.integration

RUN_ID = "run-0001"
"""The run these tests write, and the only one they assert about.

Every query below filters on it. They did not, and they passed - until the
development database held a real run and `.one()` over an unscoped table
started asking a question about somebody else's rows. An integration test
against a shared database has to say which rows are its own.
"""

GENERATED_AT = dt.datetime(2026, 10, 19, 9, 30, tzinfo=dt.UTC)
RELEASED_AT = dt.datetime(2025, 4, 1, tzinfo=dt.UTC)


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    """A session bound to one transaction that is rolled back afterwards.

    The import sits outside the skip on purpose. An earlier version wrapped it
    in the same `except Exception` as the settings lookup, and a missing name
    in the table module came back as *PostgreSQL settings unavailable* - a
    defect reported as an absent database, on a machine where the database was
    running. Only a connection failure skips; anything else is a fault here.
    """

    try:
        from app.infrastructure.postgres.database import DATABASE_URL
    except Exception as exc:  # settings come from .env; without it there is no database
        pytest.skip(f"PostgreSQL settings unavailable: {exc}")

    from app.infrastructure.postgres.models.c2_validation_run import (
        C2_TABLES,
        metadata,
    )

    engine = create_engine(DATABASE_URL, connect_args={"connect_timeout": 3})
    try:
        connection = engine.connect()
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"PostgreSQL is not reachable: {exc}")

    transaction = connection.begin()
    metadata.create_all(connection, tables=list(C2_TABLES))
    try:
        yield sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()


def verdict(fact_id: str = "f1") -> PrimaryVerdict:
    return PrimaryVerdict(
        fact_id=fact_id,
        verdict=Verdict.CONFIRMS,
        reasoning="the governing rule names this pair",
        cited_evidence_refs=("rule-frontend-cartservice",),
        model_id="openai/gpt-oss-20b",
        prompt_version="primary_verdict@1",
        evidence_hash="a" * 64,
        cached=False,
        arbiter_agreement=ArbiterAgreement.AGREED,
    )


def verification(fact_id: str = "f1") -> Verification:
    return Verification(
        fact_id=fact_id,
        outcome=VerificationOutcome.DISAGREE,
        mechanism="critical-reframing",
        reasoning="the cited line permits a different element",
        model_id="qwen/qwen3-32b",
        prompt_version="critical_reframing@1",
        cached=False,
        evidence_hash="a" * 64,
        objections=(
            Objection(
                kind=ObjectionKind.CITATION_DOES_NOT_SUPPORT,
                ref="rule-frontend-cartservice",
                statement="the policy line permits frontend, not adservice",
            ),
        ),
    )


def _mine(table):
    """Select one run's rows, which is the only thing a test may assert on."""

    return select(table).where(table.c.run_id == RUN_ID)


def run(run_id: str = RUN_ID) -> ValidationRunResult:
    fact = ClassifiedFact(
        fact_id="f1",
        bucket="needs_review",
        confidence=0.6,
        score_trace=ScoreTrace(
            terms={"verdict_base": 0.5, "source_strength_authoritative": 0.25},
            total=0.6,
            ceiling_applied="verification_disagree",
        ),
        route="review",
        governing_decision="rule-frontend-cartservice",
        source_tier=SourceTier.EXECUTABLE_CONFIG,
        evidence_refs=("rule-frontend-cartservice",),
        model_calls=2,
        source_element_id="component:a",
        target_element_id="component:b",
        relationship="communicates-with",
        produced_by="model",
        verification_outcome=VerificationOutcome.DISAGREE,
        arbiter_agreement=ArbiterAgreement.AGREED,
        verdict=verdict(),
        verification=verification(),
    )
    return ValidationRunResult(
        run_id=run_id,
        repository_id="online-boutique",
        release_id="v0.10.0",
        status="completed",
        stages=(
            StageRecord(
                name="classification",
                status=StageStatus.COMPLETED,
                counts={"facts": 1, "review": 1},
                duration_ms=4,
            ),
        ),
        facts=(fact,),
        model_calls=2,
        validation_confidence=0.6,
        generated_at=GENERATED_AT,
        released_at=RELEASED_AT,
        released_at_source="tagger",
        reasoner_model="openai/gpt-oss-20b",
        verifier_model="qwen/qwen3-32b",
        prompt_versions=("critical_reframing@1", "primary_verdict@1"),
        published_ref=f"artifacts/validated/online-boutique/v0.10.0/{RUN_ID}.graph.json",
    )


def document() -> ValidatedArchitectureGraph:
    return ValidatedArchitectureGraph(
        repository_id="online-boutique",
        release_id="v0.10.0",
        architecture_style="microservices",
        nodes=(
            ValidatedNode(
                "component:a", "frontend", "service",
                ValidationRollup(needs_review=1), canonical="frontend",
            ),
        ),
        edges=(),
        stamp=ValidationRunStamp(
            run_id=RUN_ID,
            generated_at=GENERATED_AT,
            mode=RunMode.RECONSTRUCTION,
            reasoner_model="openai/gpt-oss-20b",
            verifier_model="qwen/qwen3-32b",
        ),
        validation_confidence=0.6,
        released_at=RELEASED_AT,
        released_at_source="tagger",
        release_order_key=(0, 0, 10, 0, 0, 4, 0, 1, 0),
    )


def repository(sessions):
    from app.infrastructure.postgres.repositories.c2_run_repository import (
        PostgresRunRepository,
    )

    return PostgresRunRepository(sessions)


class TestRecordingARun:
    def test_a_run_its_stages_and_its_facts_land(self, sessions):
        from app.infrastructure.postgres.models.c2_validation_run import (
            c2_classified_fact,
            c2_stage_record,
            c2_validation_run,
        )

        repository(sessions).record(run(), document())

        with sessions() as session:
            stored = (
                session.execute(_mine(c2_validation_run)).mappings().one()
            )
            stages = session.execute(
                select(func.count())
                .select_from(c2_stage_record)
                .where(c2_stage_record.c.run_id == RUN_ID)
            )
            facts = session.execute(_mine(c2_classified_fact)).mappings().one()

        assert stored["release_id"] == "v0.10.0"
        assert stored["released_at_source"] == "tagger"
        assert stored["schema_version"] == "1.3.0"
        assert stages.scalar() == 1
        assert facts["bucket"] == "needs_review"

    def test_the_arithmetic_behind_the_number_is_stored_with_it(self, sessions):
        """A bare 0.6 invites one question. The trace is what answers it, and
        a column per term would need a migration every time a term is added."""

        from app.infrastructure.postgres.models.c2_validation_run import (
            c2_classified_fact,
        )

        repository(sessions).record(run(), document())

        with sessions() as session:
            trace = session.execute(
                select(c2_classified_fact.c.score_trace).where(
                    c2_classified_fact.c.run_id == RUN_ID
                )
            ).scalar_one()

        assert trace["total"] == 0.6
        assert trace["ceiling_applied"] == "verification_disagree"
        assert sum(trace["terms"].values()) > trace["total"]

    def test_both_model_outputs_are_kept_in_full(self, sessions):
        """The reasoning sentence and the objections are the only parts of the
        output a model actually produced. A result that cannot show them is an
        assertion rather than evidence."""

        from app.infrastructure.postgres.models.c2_validation_run import (
            c2_objection,
            c2_primary_verdict,
            c2_verification,
        )

        repository(sessions).record(run(), document())

        with sessions() as session:
            stored_verdict = session.execute(_mine(c2_primary_verdict)).mappings().one()
            stored_check = session.execute(_mine(c2_verification)).mappings().one()
            objection = session.execute(_mine(c2_objection)).mappings().one()

        assert stored_verdict["reasoning"].startswith("the governing rule")
        assert stored_verdict["model_id"] == "openai/gpt-oss-20b"
        assert stored_check["model_id"] == "qwen/qwen3-32b"
        assert stored_check["evidence_hash"] == stored_verdict["evidence_hash"]
        assert objection["ref"] == "rule-frontend-cartservice"

    def test_the_two_verdicts_can_be_joined_on_one_fact(self, sessions):
        """The query the whole relational model exists to serve: did the two
        models fail on the same facts. Impossible once either is reduced to a
        verdict word."""

        from app.infrastructure.postgres.models.c2_validation_run import (
            c2_primary_verdict,
            c2_verification,
        )

        repository(sessions).record(run(), document())

        with sessions() as session:
            rows = session.execute(
                select(
                    c2_primary_verdict.c.verdict, c2_verification.c.outcome
                ).join_from(
                    c2_primary_verdict,
                    c2_verification,
                    (c2_primary_verdict.c.run_id == c2_verification.c.run_id)
                    & (c2_primary_verdict.c.fact_id == c2_verification.c.fact_id),
                )
                .where(c2_primary_verdict.c.run_id == RUN_ID)
            ).all()

        assert rows == [("confirms", "disagree")]

    def test_re_recording_one_run_replaces_it_rather_than_duplicating_it(
        self, sessions
    ):
        """A second recording of one run means the first was interrupted.
        Replacing it is the only reading that leaves the table describing what
        happened once."""

        from app.infrastructure.postgres.models.c2_validation_run import (
            c2_classified_fact,
        )

        store = repository(sessions)
        store.record(run(), document())
        store.record(run(), document())

        with sessions() as session:
            facts = session.execute(
                select(func.count())
                .select_from(c2_classified_fact)
                .where(c2_classified_fact.c.run_id == RUN_ID)
            ).scalar()

        assert facts == 1

    def test_the_element_rollups_land_with_an_identity_that_survives_a_move(
        self, sessions
    ):
        from app.infrastructure.postgres.models.c2_validation_run import c2_element

        repository(sessions).record(run(), document())

        with sessions() as session:
            element = session.execute(_mine(c2_element)).mappings().one()

        assert element["element_id"] == "component:a"
        assert element["canonical"] == "frontend"
        assert element["needs_review"] == 1
