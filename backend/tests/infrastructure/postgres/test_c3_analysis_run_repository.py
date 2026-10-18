"""PostgresAnalysisRunRepository against a real database (Docker: ``docker compose up -d``).

Every test runs inside one outer transaction that is rolled back, tables included, so the
development database is left as it was. Skips when PostgreSQL is not reachable.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.domain.analysis_run import RunOutputs, StoredRun
from tests.components.degradation_detection.run_records import (
    ARTIFACTS,
    RUN_ID,
    completed_run,
    failed_run,
    outputs,
    started_run,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    try:
        from app.infrastructure.postgres.database import DATABASE_URL
        from app.infrastructure.postgres.models.c3_analysis_run import C3_RUN_TABLES, metadata
    except Exception as exc:  # settings come from .env; without it there is no database
        pytest.skip(f"PostgreSQL settings unavailable: {exc}")

    engine = create_engine(DATABASE_URL, connect_args={"connect_timeout": 3})
    try:
        connection = engine.connect()
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"PostgreSQL not reachable: {exc.orig}")

    outer = connection.begin()
    metadata.create_all(connection, tables=C3_RUN_TABLES)  # no-op when the migration has run
    yield sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    outer.rollback()
    connection.close()
    engine.dispose()


@pytest.fixture
def repo(sessions: sessionmaker[Session]) -> Any:
    from app.infrastructure.postgres.repositories.c3_analysis_run_repository import (
        PostgresAnalysisRunRepository,
    )

    return PostgresAnalysisRunRepository(sessions)


def test_unknown_run_loads_as_none(repo: Any) -> None:
    assert repo.load(RUN_ID) is None


def test_started_run_loads_running_with_no_outputs(repo: Any) -> None:
    repo.start(started_run())

    assert repo.load(RUN_ID) == StoredRun(run=started_run(), outputs=RunOutputs())


def test_completed_run_round_trips(repo: Any) -> None:
    repo.start(started_run())
    repo.complete(completed_run(), outputs(), ARTIFACTS)

    assert repo.load(RUN_ID) == StoredRun(run=completed_run(), outputs=outputs())


def test_artifacts_are_stored_as_json(repo: Any, sessions: sessionmaker[Session]) -> None:
    from app.infrastructure.postgres.models.c3_analysis_run import c3_run_artifact

    repo.start(started_run())
    repo.complete(completed_run(), outputs(), ARTIFACTS)

    with sessions() as session:
        stored = dict(
            session.execute(
                select(c3_run_artifact.c.name, c3_run_artifact.c.payload).where(
                    c3_run_artifact.c.run_id == RUN_ID
                )
            ).all()
        )
    assert stored == ARTIFACTS


def test_failed_run_keeps_its_error(repo: Any) -> None:
    repo.start(started_run())
    repo.fail(failed_run())

    assert repo.load(RUN_ID) == StoredRun(run=failed_run(), outputs=RunOutputs())


def test_a_run_id_is_stored_once(repo: Any) -> None:
    repo.start(started_run())

    with pytest.raises(IntegrityError):
        repo.start(started_run())


def test_only_a_running_run_can_finish(repo: Any) -> None:
    with pytest.raises(LookupError):
        repo.fail(failed_run())

    repo.start(started_run())
    repo.fail(failed_run())
    with pytest.raises(LookupError):
        repo.complete(completed_run(), outputs(), ARTIFACTS)
