"""PostgresReleaseRepository against a real database (Docker: ``docker compose up -d``).

Every test runs inside one outer transaction that is rolled back, tables included, so the
development database is left as it was. Skips when PostgreSQL is not reachable.
"""

import datetime as dt
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.domain.canonical_release import (
    CanonicalRelease,
    DatastoreAccess,
    DependencyEdge,
    ElementSnapshot,
    GateStatus,
    IntentEntry,
)
from app.domain.release_package import ArchitectureStyle

pytestmark = pytest.mark.integration

INGESTED_AT = dt.datetime(2026, 10, 15, 9, 30, tzinfo=dt.UTC)


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    try:
        from app.infrastructure.postgres.database import DATABASE_URL
        from app.infrastructure.postgres.models.c3_release import C3_TABLES, metadata
    except Exception as exc:  # settings come from .env; without it there is no database
        pytest.skip(f"PostgreSQL settings unavailable: {exc}")

    engine = create_engine(DATABASE_URL, connect_args={"connect_timeout": 3})
    try:
        connection = engine.connect()
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"PostgreSQL not reachable: {exc.orig}")

    outer = connection.begin()
    metadata.create_all(connection, tables=C3_TABLES)  # no-op when the migration has run
    yield sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    outer.rollback()
    connection.close()
    engine.dispose()


@pytest.fixture
def repo(sessions: sessionmaker[Session]) -> Any:
    from app.infrastructure.postgres.repositories.c3_release_repository import (
        PostgresReleaseRepository,
    )

    return PostgresReleaseRepository(sessions)


def release(release_id: str = "v1.0.0", **overrides: Any) -> CanonicalRelease:
    fields: dict[str, Any] = {
        "system_id": "tiny",
        "release_id": release_id,
        "released_at": dt.datetime(2025, 1, 1, 3, tzinfo=dt.timezone(dt.timedelta(hours=5))),
        "architecture_style": ArchitectureStyle.MICROSERVICES,
        "granularity": "service",
        "validation_confidence": 0.83,
        "gate_status": GateStatus.DOWNWEIGHTED,
        "package_hash": "sha256:" + "ab" * 32,
        "elements": (
            ElementSnapshot(
                element_id="a",
                name="A",
                kind="service",
                size=1234.5,
                size_unit="loc",
                aliases=("a-old", "a-older"),
                layer="domain",
                metrics={"c1.lcom": 0.42, "c1.wmc": None},
                extra={"team": "x", "tags": [1, 2]},
            ),
            ElementSnapshot(element_id="b", name="b", kind="service"),
        ),
        "dependencies": (DependencyEdge(from_id="a", to_id="b", types=("call", "event"), count=3),),
        "intent": (
            IntentEntry(
                intent_id="ADR-1",
                element_id="a",
                source_type="adr",
                ref="ADR-1",
                decision="split a",
                decision_kind="split",
                date=dt.date(2025, 1, 2),
            ),
        ),
        "datastore_access": (
            DatastoreAccess(element_id="a", datastore="orders_db", mode="readwrite"),
            DatastoreAccess(element_id="b", datastore="orders_db"),
        ),
        "delegation": ({"from": "a", "to": "b", "call": "x"},),
        "c1_model_ref": "c1://tiny/v1.0.0",
        "c2_validation_ref": None,
    }
    return CanonicalRelease.model_validate(fields | overrides)


def test_release_round_trips(repo: Any) -> None:
    original = release()

    repo.add(original, {"raw": True}, INGESTED_AT)

    [loaded] = repo.list_releases("tiny")
    assert loaded == original
    assert loaded.released_at == original.released_at  # same instant, stored as timestamptz


def test_not_supplied_optional_inputs_stay_none_and_empty_stays_empty(repo: Any) -> None:
    repo.add(release("v1", datastore_access=None, delegation=None), {}, INGESTED_AT)
    repo.add(release("v2", datastore_access=(), delegation=()), {}, INGESTED_AT)

    by_id = {r.release_id: r for r in repo.list_releases("tiny")}
    assert (by_id["v1"].datastore_access, by_id["v1"].delegation) == (None, None)
    assert (by_id["v2"].datastore_access, by_id["v2"].delegation) == ((), ())


def test_find_package_hash(repo: Any) -> None:
    assert repo.find_package_hash("tiny", "v1.0.0") is None

    repo.add(release(), {}, INGESTED_AT)

    assert repo.find_package_hash("tiny", "v1.0.0") == "sha256:" + "ab" * 32
    assert repo.find_package_hash("other", "v1.0.0") is None


def test_list_is_scoped_to_one_system(repo: Any) -> None:
    repo.add(release(), {}, INGESTED_AT)
    repo.add(release(system_id="other"), {}, INGESTED_AT)

    assert [r.system_id for r in repo.list_releases("tiny")] == ["tiny"]
    assert repo.list_releases("nobody") == ()


def test_raw_payload_and_ingest_time_are_stored(repo: Any, sessions: sessionmaker[Session]) -> None:
    from app.infrastructure.postgres.models.c3_release import c3_release

    repo.add(release(), {"system_id": "tiny", "colour": "blue"}, INGESTED_AT)

    with sessions() as session:
        row = session.execute(select(c3_release.c.raw_json, c3_release.c.ingested_at)).one()
    assert row.raw_json == {"system_id": "tiny", "colour": "blue"}
    assert row.ingested_at == INGESTED_AT


def test_same_release_twice_is_refused_by_the_key(repo: Any) -> None:
    repo.add(release(), {}, INGESTED_AT)

    with pytest.raises(IntegrityError):
        repo.add(release(), {}, INGESTED_AT)


def test_replace_overwrites_the_release_and_its_children(repo: Any) -> None:
    repo.add(release(), {"v": 1}, INGESTED_AT)
    newer = release(validation_confidence=0.55, package_hash="sha256:" + "cd" * 32, intent=())

    repo.replace(newer, {"v": 2}, INGESTED_AT)

    assert repo.list_releases("tiny") == (newer,)


def test_replace_of_a_release_never_stored_is_refused(repo: Any) -> None:
    with pytest.raises(LookupError):
        repo.replace(release(), {}, INGESTED_AT)
    assert repo.list_releases("tiny") == ()
