# PostgresScoringRunRepository against a real database (Docker), C4-T16b (scores: C4-T19).
# Each test runs in one outer transaction that is rolled back; skips without PostgreSQL.

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.components.degradation_scoring.service import (
    DegradationScoringService,
    feature_rows,
    ingestion_rows,
    run_row,
    score_rows,
)
from tests.components.degradation_scoring.support import (
    adr_index_document,
    default_config,
    load_fixture,
)

pytestmark = pytest.mark.integration

RUN = DegradationScoringService(default_config()).run_features(
    load_fixture("events/fixture_events.v1.json"),
    load_fixture("graphs/fixture_release_package.v1.5.0.json"),
    run_id="pytest-run",
    data_provenance="fixture",
    adr_document=adr_index_document(),
)


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    try:
        from app.infrastructure.postgres.database import DATABASE_URL
        from app.infrastructure.postgres.models.c4_scoring_run import C4_RUN_TABLES, metadata
    except Exception as exc:  # settings come from .env; without it there is no database
        pytest.skip(f"PostgreSQL settings unavailable: {exc}")

    engine = create_engine(DATABASE_URL, connect_args={"connect_timeout": 3})
    try:
        connection = engine.connect()
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"PostgreSQL not reachable: {exc.orig}")

    outer = connection.begin()
    metadata.create_all(connection, tables=C4_RUN_TABLES)  # no-op when the migration has run
    yield sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    outer.rollback()
    connection.close()
    engine.dispose()


@pytest.fixture
def repo(sessions: sessionmaker[Session]) -> Any:
    from app.infrastructure.postgres.repositories.scoring_run_repository import (
        PostgresScoringRunRepository,
    )

    return PostgresScoringRunRepository(sessions)


def save(repo: Any, run_id: str = "pytest-run") -> None:
    run = RUN.model_copy(update={"run_id": run_id})
    repo.save(
        run_row(run, "fixture", None, None), ingestion_rows(run), feature_rows(run), score_rows(run)
    )


def count(sessions: sessionmaker[Session], table: Any, run_id: str = "pytest-run") -> int:
    with sessions() as session:
        return int(
            session.execute(
                select(func.count()).select_from(table).where(table.c.run_id == run_id)
            ).scalar_one()
        )


def test_a_run_is_stored_with_all_its_rows(repo: Any, sessions: sessionmaker[Session]) -> None:
    from app.infrastructure.postgres.models.c4_scoring_run import (
        c4_event_features,
        c4_event_ingestion,
        c4_event_scores,
        c4_scoring_run,
    )

    save(repo)

    assert count(sessions, c4_scoring_run) == 1
    assert count(sessions, c4_event_ingestion) == 17
    assert count(sessions, c4_event_features) == 9
    assert count(sessions, c4_event_scores) == 9


def test_values_round_trip(repo: Any, sessions: sessionmaker[Session]) -> None:
    from app.infrastructure.postgres.models.c4_scoring_run import (
        c4_event_features,
        c4_event_ingestion,
        c4_scoring_run,
    )

    save(repo)

    f, i, r = c4_event_features.c, c4_event_ingestion.c, c4_scoring_run.c
    with sessions() as session:
        av, adr, fan_in = session.execute(
            select(f.av_weight, f.av_adr_id, f.br_fan_in_ratio).where(
                f.run_id == "pytest-run", f.event_id == "DEG-C4FX-R02-0001"
            )
        ).one()
        nodes, malformed_id = session.execute(
            select(i.nodes, i.event_id).where(i.run_id == "pytest-run", i.payload_index == 14)
        ).one()
        details = session.execute(select(r.details).where(r.run_id == "pytest-run")).scalar_one()

    assert (av, adr) == (1.0, "ADR-0001")
    assert fan_in == pytest.approx(7 / 18)
    assert (nodes, malformed_id) == ([], None)  # a malformed payload without an id
    assert details["adr_scope_weights"]["local"] == 0.4
    assert details["scoring"]["weights_provenance"] == "provisional-author-elicited"


def test_scores_round_trip_in_rank_order(repo: Any, sessions: sessionmaker[Session]) -> None:
    from app.infrastructure.postgres.models.c4_scoring_run import c4_event_scores

    save(repo)

    s = c4_event_scores.c
    with sessions() as session:
        rows = session.execute(
            select(s.event_id, s.rank, s.severity, s.av_weight, s.eh_normalized, s.eh_weight)
            .where(s.run_id == "pytest-run")
            .order_by(s.rank)
        ).all()

    expected = score_rows(RUN.model_copy(update={"run_id": "pytest-run"}))
    assert [(r.event_id, r.rank) for r in rows] == [(e["event_id"], e["rank"]) for e in expected]
    assert [r.severity for r in rows] == pytest.approx([e["severity"] for e in expected])
    assert rows[0].av_weight == pytest.approx(0.2215, abs=1e-4)  # AV on in this run
    assert (rows[0].eh_normalized, rows[0].eh_weight) == (None, 0.0)  # hotspot off


def test_reusing_a_run_id_fails_and_stores_nothing_more(
    repo: Any, sessions: sessionmaker[Session]
) -> None:
    from app.infrastructure.postgres.models.c4_scoring_run import c4_event_ingestion

    save(repo)
    with pytest.raises(IntegrityError):
        save(repo)

    assert count(sessions, c4_event_ingestion) == 17


def test_deleting_a_run_deletes_its_rows(repo: Any, sessions: sessionmaker[Session]) -> None:
    from app.infrastructure.postgres.models.c4_scoring_run import (
        c4_event_features,
        c4_event_ingestion,
        c4_event_scores,
        c4_scoring_run,
    )

    save(repo)
    with sessions() as session, session.begin():
        session.execute(delete(c4_scoring_run).where(c4_scoring_run.c.run_id == "pytest-run"))

    assert count(sessions, c4_event_ingestion) == 0
    assert count(sessions, c4_event_features) == 0
    assert count(sessions, c4_event_scores) == 0
