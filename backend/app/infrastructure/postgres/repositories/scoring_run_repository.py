# PostgreSQL implementation of C4's ScoringRunRepository port (C4-T16b).

from collections.abc import Mapping, Sequence

from sqlalchemy import insert
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.postgres.models.c4_scoring_run import (
    c4_event_features,
    c4_event_ingestion,
    c4_scoring_run,
)


class PostgresScoringRunRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def save(
        self,
        run: Mapping[str, object],
        ingestion: Sequence[Mapping[str, object]],
        features: Sequence[Mapping[str, object]],
    ) -> None:
        # one transaction: a run is stored completely or not at all; a reused run_id fails
        with self._sessions() as session, session.begin():
            session.execute(insert(c4_scoring_run).values(**run))
            if ingestion:
                session.execute(insert(c4_event_ingestion), [dict(row) for row in ingestion])
            if features:
                session.execute(insert(c4_event_features), [dict(row) for row in features])
