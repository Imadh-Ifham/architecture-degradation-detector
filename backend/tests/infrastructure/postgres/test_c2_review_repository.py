"""PostgresReviewQueueRepository against a real database (Docker: ``docker compose up -d``).

Every test runs inside one outer transaction that is rolled back, tables included, so the
development database is left as it was. Skips only when PostgreSQL is not reachable - an import
failure is a fault here, not an absent database, which is a distinction an earlier version of the
sibling module got wrong and hid a missing import behind for one run.

Every query is scoped to the items this test wrote. An unscoped ``.one()`` is an assertion about
the whole development database rather than about what the test did, and it passes right up until
somebody runs the demonstration script.
"""

import datetime as dt
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.components.architecture_validation.architect_review.models import (
    ReviewDecision,
    ReviewStatus,
)
from app.components.architecture_validation.models import ReviewItem, SourceTier

pytestmark = pytest.mark.integration

REPOSITORY = "review-repository-test"
RELEASE = "v0.10.0"
CREATED_AT = dt.datetime(2026, 10, 19, 9, 30, tzinfo=dt.UTC)
DECIDED_AT = dt.datetime(2026, 10, 19, 11, 0, tzinfo=dt.UTC)


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    try:
        from app.infrastructure.postgres.database import DATABASE_URL
    except Exception as exc:  # settings come from .env; without it there is no database
        pytest.skip(f"PostgreSQL settings unavailable: {exc}")

    from app.infrastructure.postgres.models.c2_review_item import (
        C2_REVIEW_TABLES,
        metadata,
    )

    engine = create_engine(DATABASE_URL, connect_args={"connect_timeout": 3})
    try:
        connection = engine.connect()
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"PostgreSQL is not reachable: {exc}")

    transaction = connection.begin()
    metadata.create_all(connection, tables=list(C2_REVIEW_TABLES))
    try:
        yield sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()


def queue(sessions):
    from app.infrastructure.postgres.repositories.c2_review_repository import (
        PostgresReviewQueueRepository,
    )

    return PostgresReviewQueueRepository(sessions, REPOSITORY, RELEASE)


def item(fact_id: str = "f1", item_id: str = "item-1") -> ReviewItem:
    return ReviewItem(
        item_id=item_id,
        fact_id=fact_id,
        bucket="needs_review",
        confidence=0.6,
        source_tier=SourceTier.DOCUMENTATION,
        evidence_refs=("rule-candidate-1",),
        candidate_decision_id="rule-candidate-1",
        created_at=CREATED_AT,
    )


def rows(sessions) -> int:
    from app.infrastructure.postgres.models.c2_review_item import c2_review_item

    with sessions() as session:
        return session.execute(
            select(func.count())
            .select_from(c2_review_item)
            .where(c2_review_item.c.repository_id == REPOSITORY)
        ).scalar()


class TestTheQueue:
    def test_an_item_round_trips(self, sessions):
        store = queue(sessions)

        store.enqueue(item())
        stored = store.get("item-1")

        assert stored is not None
        assert stored.fact_id == "f1"
        assert stored.source_tier is SourceTier.DOCUMENTATION
        assert stored.evidence_refs == ("rule-candidate-1",)
        assert stored.status == str(ReviewStatus.PENDING)

    def test_an_unknown_item_is_none_rather_than_an_error(self, sessions):
        """A queue that raises on a missing item would make the route's 404
        indistinguishable from a database fault."""

        assert queue(sessions).get("nope") is None

    def test_enqueueing_the_same_item_twice_writes_one_row(self, sessions):
        """The unique constraint doing the work, in one statement. Two runs of
        one release can overlap, and a check that passed before an insert is
        not a guarantee."""

        store = queue(sessions)

        store.enqueue(item())
        store.enqueue(item())

        assert rows(sessions) == 1

    def test_a_re_enqueue_does_not_reopen_a_decided_item(self, sessions):
        """The consequence that matters: a settled question must not depend on
        how many times the pipeline ran afterwards."""

        store = queue(sessions)
        store.enqueue(item())
        store.resolve(
            ReviewDecision(
                item_id="item-1",
                accepted=True,
                decided_by="architect",
                decided_at=DECIDED_AT,
            )
        )

        store.enqueue(item())

        assert store.get("item-1").status == str(ReviewStatus.ACCEPTED)

    def test_pending_is_oldest_first_and_excludes_decided_items(self, sessions):
        """Oldest first, because a queue read newest-first buries the item
        that has been waiting longest."""

        store = queue(sessions)
        store.enqueue(item("f1", "item-1"))
        store.enqueue(
            ReviewItem(
                item_id="item-2",
                fact_id="f2",
                bucket="needs_review",
                confidence=0.6,
                source_tier=SourceTier.HISTORY,
                evidence_refs=(),
                candidate_decision_id=None,
                created_at=CREATED_AT + dt.timedelta(hours=1),
            )
        )
        store.resolve(
            ReviewDecision(
                item_id="item-1",
                accepted=False,
                decided_by="architect",
                decided_at=DECIDED_AT,
            )
        )

        waiting = [i.item_id for i in store.pending() if i.item_id.startswith("item-")]

        assert waiting == ["item-2"]

    def test_a_rejection_is_stored_exactly_as_a_confirmation_is(self, sessions):
        """It says a mined candidate was wrong, which is the only ground truth
        this system produces for free."""

        from app.infrastructure.postgres.models.c2_review_item import c2_review_item

        store = queue(sessions)
        store.enqueue(item())
        store.resolve(
            ReviewDecision(
                item_id="item-1",
                accepted=False,
                decided_by="architect",
                decided_at=DECIDED_AT,
                note="we removed that boundary last quarter",
            )
        )

        with sessions() as session:
            row = session.execute(
                select(c2_review_item).where(c2_review_item.c.item_id == "item-1")
            ).mappings().one()

        assert row["status"] == str(ReviewStatus.REJECTED)
        assert row["decided_by"] == "architect"
        assert row["decided_at"] == DECIDED_AT
        assert row["note"] == "we removed that boundary last quarter"
