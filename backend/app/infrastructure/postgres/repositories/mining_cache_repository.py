# PostgreSQL implementation of C4's MiningCache port (C4-T12, C4-ADR-001).

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.postgres.models.c4_mining_cache import c4_mining_cache


class PostgresMiningCache:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def get(
        self, repo_path: str, from_tag: str, to_tag: str, filter_hash: str
    ) -> list[dict[str, Any]] | None:
        query = select(c4_mining_cache.c.rows).where(
            c4_mining_cache.c.repo_path == repo_path,
            c4_mining_cache.c.from_tag == from_tag,
            c4_mining_cache.c.to_tag == to_tag,
            c4_mining_cache.c.filter_hash == filter_hash,
        )
        with self._sessions() as session:
            rows: list[dict[str, Any]] | None = session.execute(query).scalar_one_or_none()
        return rows

    def put(
        self,
        repo_path: str,
        from_tag: str,
        to_tag: str,
        filter_hash: str,
        rows: Sequence[Mapping[str, object]],
    ) -> None:
        # re-mining the same range replaces the entry
        values = {
            "commit_count": len(rows),
            "rows": [dict(row) for row in rows],
            "mined_at": dt.datetime.now(dt.UTC),
        }
        statement = (
            insert(c4_mining_cache)
            .values(
                repo_path=repo_path,
                from_tag=from_tag,
                to_tag=to_tag,
                filter_hash=filter_hash,
                **values,
            )
            .on_conflict_do_update(index_elements=c4_mining_cache.primary_key.columns, set_=values)
        )
        with self._sessions() as session, session.begin():
            session.execute(statement)
