# PostgresMiningCache against a real database (Docker: docker compose up -d), C4-T12.
# Each test runs in one outer transaction that is rolled back; skips without PostgreSQL.

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.integration

KEY = ("C:/repos/demo", "v1.0.0", "v1.1.0", "sha256:abc")
ROWS: list[dict[str, Any]] = [
    {
        "hash": "a1",
        "author_email": "alice@example.com",
        "committed_at": "2026-01-05T12:00:00+00:00",
        "message": "order: rework totals",
        "files": [{"path": "src/order/OrderService.java", "added": 4, "deleted": 1}],
    }
]


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    try:
        from app.infrastructure.postgres.database import DATABASE_URL
        from app.infrastructure.postgres.models.c4_mining_cache import C4_TABLES, metadata
    except Exception as exc:  # settings come from .env; without it there is no database
        pytest.skip(f"PostgreSQL settings unavailable: {exc}")

    engine = create_engine(DATABASE_URL, connect_args={"connect_timeout": 3})
    try:
        connection = engine.connect()
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"PostgreSQL not reachable: {exc.orig}")

    outer = connection.begin()
    metadata.create_all(connection, tables=C4_TABLES)  # no-op when the migration has run
    yield sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    outer.rollback()
    connection.close()
    engine.dispose()


@pytest.fixture
def cache(sessions: sessionmaker[Session]) -> Any:
    from app.infrastructure.postgres.repositories.mining_cache_repository import (
        PostgresMiningCache,
    )

    return PostgresMiningCache(sessions)


def test_unknown_range_is_a_miss(cache: Any) -> None:
    assert cache.get(*KEY) is None


def test_round_trip(cache: Any) -> None:
    cache.put(*KEY, ROWS)

    assert cache.get(*KEY) == ROWS


def test_empty_range_is_cached_as_empty(cache: Any) -> None:
    cache.put(*KEY, [])

    assert cache.get(*KEY) == []


def test_each_key_part_matters(cache: Any) -> None:
    cache.put(*KEY, ROWS)

    for position, other in enumerate(["C:/repos/other", "v0.9.0", "v1.2.0", "sha256:def"]):
        key = list(KEY)
        key[position] = other
        assert cache.get(*key) is None


def test_putting_again_replaces_the_entry(cache: Any, sessions: sessionmaker[Session]) -> None:
    from app.infrastructure.postgres.models.c4_mining_cache import c4_mining_cache

    cache.put(*KEY, ROWS)
    cache.put(*KEY, [*ROWS, {**ROWS[0], "hash": "b2"}])

    with sessions() as session:
        count, commits = session.execute(
            select(func.count(), func.max(c4_mining_cache.c.commit_count))
        ).one()
    assert (count, commits) == (1, 2)
    assert [row["hash"] for row in cache.get(*KEY)] == ["a1", "b2"]
