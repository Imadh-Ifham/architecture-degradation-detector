"""PostgreSQL implementation of the C3 ``ReleaseRepository`` port (M1 persistence)."""

import datetime as dt
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import Row, Table, insert, select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.canonical_release import (
    CanonicalRelease,
    DatastoreAccess,
    DependencyEdge,
    ElementSnapshot,
    IntentEntry,
)
from app.infrastructure.postgres.models.c3_release import (
    c3_datastore_access,
    c3_dependency_edge,
    c3_element_snapshot,
    c3_intent_entry,
    c3_release,
)

ReleaseKey = tuple[str, str]


def _children(
    session: Session, table: Table, system_id: str, order_by: Iterable[str]
) -> dict[ReleaseKey, list[Row[Any]]]:
    query = (
        select(table)
        .where(table.c.system_id == system_id)
        .order_by(table.c.release_id, *(table.c[name] for name in order_by))
    )
    grouped: dict[ReleaseKey, list[Row[Any]]] = defaultdict(list)
    for row in session.execute(query):
        grouped[(row.system_id, row.release_id)].append(row)
    return grouped


class PostgresReleaseRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def find_package_hash(self, system_id: str, release_id: str) -> str | None:
        query = select(c3_release.c.package_hash).where(
            c3_release.c.system_id == system_id, c3_release.c.release_id == release_id
        )
        with self._sessions() as session:
            found: str | None = session.execute(query).scalar_one_or_none()
        return found

    def add(
        self,
        release: CanonicalRelease,
        raw_payload: Mapping[str, Any],
        ingested_at: dt.datetime,
    ) -> None:
        key = {"system_id": release.system_id, "release_id": release.release_id}
        # JSON mode turns tuples into lists for the JSONB columns.
        children: list[tuple[Table, list[dict[str, Any]]]] = [
            (
                c3_element_snapshot,
                [key | element.model_dump(mode="json") for element in release.elements],
            ),
            (
                c3_dependency_edge,
                [key | edge.model_dump(mode="json") for edge in release.dependencies],
            ),
            (
                c3_datastore_access,
                [
                    key | {"position": i} | access.model_dump()
                    for i, access in enumerate(release.datastore_access or ())
                ],
            ),
            (
                c3_intent_entry,
                [
                    key | {"position": i} | intent.model_dump()
                    for i, intent in enumerate(release.intent)
                ],
            ),
        ]
        # One transaction per package: either the whole release is stored or none of it.
        with self._sessions.begin() as session:
            session.execute(
                insert(c3_release).values(
                    **key,
                    released_at=release.released_at,
                    architecture_style=release.architecture_style.value,
                    granularity=release.granularity,
                    validation_confidence=release.validation_confidence,
                    gate_status=release.gate_status.value,
                    package_hash=release.package_hash,
                    c1_model_ref=release.c1_model_ref,
                    c2_validation_ref=release.c2_validation_ref,
                    datastore_access_supplied=release.datastore_access is not None,
                    delegation=None if release.delegation is None else list(release.delegation),
                    raw_json=dict(raw_payload),
                    ingested_at=ingested_at,
                )
            )
            for table, rows in children:
                if rows:
                    session.execute(insert(table), rows)

    def list_releases(self, system_id: str) -> tuple[CanonicalRelease, ...]:
        with self._sessions() as session:
            releases = session.execute(
                select(c3_release)
                .where(c3_release.c.system_id == system_id)
                .order_by(c3_release.c.release_id)
            ).all()
            elements = _children(session, c3_element_snapshot, system_id, ["element_id"])
            edges = _children(session, c3_dependency_edge, system_id, ["from_id", "to_id"])
            accesses = _children(session, c3_datastore_access, system_id, ["position"])
            intents = _children(session, c3_intent_entry, system_id, ["position"])

        result = []
        for row in releases:
            key = (row.system_id, row.release_id)
            result.append(
                CanonicalRelease(
                    system_id=row.system_id,
                    release_id=row.release_id,
                    released_at=row.released_at,
                    architecture_style=row.architecture_style,
                    granularity=row.granularity,
                    validation_confidence=row.validation_confidence,
                    gate_status=row.gate_status,
                    package_hash=row.package_hash,
                    elements=tuple(
                        ElementSnapshot(
                            element_id=e.element_id,
                            name=e.name,
                            kind=e.kind,
                            size=e.size,
                            size_unit=e.size_unit,
                            aliases=tuple(e.aliases),
                            layer=e.layer,
                            metrics=e.metrics,
                            extra=e.extra,
                        )
                        for e in elements[key]
                    ),
                    dependencies=tuple(
                        DependencyEdge(
                            from_id=d.from_id,
                            to_id=d.to_id,
                            types=tuple(d.types),
                            count=d._mapping["count"],
                        )
                        for d in edges[key]
                    ),
                    intent=tuple(
                        IntentEntry(
                            intent_id=i.intent_id,
                            element_id=i.element_id,
                            source_type=i.source_type,
                            ref=i.ref,
                            decision=i.decision,
                            decision_kind=i.decision_kind,
                            date=i.date,
                        )
                        for i in intents[key]
                    ),
                    datastore_access=(
                        tuple(
                            DatastoreAccess(
                                element_id=a.element_id, datastore=a.datastore, mode=a.mode
                            )
                            for a in accesses[key]
                        )
                        if row.datastore_access_supplied
                        else None
                    ),
                    delegation=None if row.delegation is None else tuple(row.delegation),
                    c1_model_ref=row.c1_model_ref,
                    c2_validation_ref=row.c2_validation_ref,
                )
            )
        return tuple(result)
