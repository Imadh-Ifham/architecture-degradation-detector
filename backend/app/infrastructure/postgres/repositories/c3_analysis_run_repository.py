"""PostgreSQL implementation of the C3 ``AnalysisRunRepository`` port (T-13)."""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Row, Table, insert, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.domain.analysis_run import (
    AnalysisRun,
    InstanceRecord,
    RunOutputs,
    RunRelease,
    RunStatus,
    SeriesPointRecord,
    StaticFlag,
    StoredRun,
    TrendRecord,
    UntestedRecord,
)
from app.domain.degradation_event import DegradationEventV2
from app.infrastructure.postgres.models.c3_analysis_run import (
    c3_analysis_run,
    c3_ap_instance,
    c3_degradation_event,
    c3_run_artifact,
    c3_static_flag,
    c3_trend_result,
)


def _run_values(run: AnalysisRun) -> dict[str, Any]:
    """The columns a run's own row holds (everything but its id)."""
    return {
        "system_id": run.system_id,
        "status": run.status.value,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "config": run.config,
        "config_hash": run.config_hash,
        "code_version": run.code_version,
        "lib_versions": run.lib_versions,
        "releases": [release.model_dump(mode="json") for release in run.releases],
        "timings": run.timings,
        "reason_counts": run.reason_counts,
        "error": run.error,
    }


def _trend_row(trend: TrendRecord) -> dict[str, Any]:
    row = trend.model_dump(mode="json", exclude={"n"})
    return row | {"n_points": trend.n, "untested_reason": None}


def _untested_row(untested: UntestedRecord) -> dict[str, Any]:
    row = untested.model_dump(mode="json", exclude={"reason"})
    return row | {"untested_reason": untested.reason}


def _rows(run_id: str, values: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"run_id": run_id, "position": i} | value for i, value in enumerate(values)]


def _ordered(session: Session, table: Table, run_id: str, *where: Any) -> list[Row[Any]]:
    query = select(table).where(table.c.run_id == run_id, *where).order_by(table.c.position)
    return list(session.execute(query).all())


class PostgresAnalysisRunRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def start(self, run: AnalysisRun) -> None:
        with self._sessions.begin() as session:
            session.execute(insert(c3_analysis_run).values(run_id=run.run_id, **_run_values(run)))

    def complete(self, run: AnalysisRun, outputs: RunOutputs, artifacts: Mapping[str, Any]) -> None:
        children: list[tuple[Table, list[dict[str, Any]]]] = [
            (
                c3_ap_instance,
                _rows(run.run_id, [i.model_dump(mode="json") for i in outputs.instances]),
            ),
            (c3_trend_result, _rows(run.run_id, [_trend_row(t) for t in outputs.trends])),
            (c3_trend_result, _rows(run.run_id, [_untested_row(u) for u in outputs.untested])),
            (
                c3_degradation_event,
                _rows(
                    run.run_id,
                    [
                        {
                            "event_id": e.event_id,
                            "event_key": e.event_key,
                            "scope": e.scope.value,
                            "anti_pattern_type": e.anti_pattern_type,
                            "payload": e.model_dump(mode="json"),
                        }
                        for e in outputs.events
                    ],
                ),
            ),
            (
                c3_static_flag,
                _rows(run.run_id, [f.model_dump(mode="json") for f in outputs.static_flags]),
            ),
        ]
        artifact_rows = [
            {"run_id": run.run_id, "name": name, "payload": payload}
            for name, payload in artifacts.items()
        ]
        # One transaction: the run is COMPLETED with all its outputs, or not at all.
        with self._sessions.begin() as session:
            self._finish(session, run)
            for table, rows in [*children, (c3_run_artifact, artifact_rows)]:
                if rows:
                    session.execute(insert(table), rows)

    def fail(self, run: AnalysisRun) -> None:
        with self._sessions.begin() as session:
            self._finish(session, run)

    def load(self, run_id: str) -> StoredRun | None:
        with self._sessions() as session:
            row = session.execute(
                select(c3_analysis_run).where(c3_analysis_run.c.run_id == run_id)
            ).one_or_none()
            if row is None:
                return None
            instances = _ordered(session, c3_ap_instance, run_id)
            tested = _ordered(
                session, c3_trend_result, run_id, c3_trend_result.c.untested_reason.is_(None)
            )
            untested = _ordered(
                session, c3_trend_result, run_id, c3_trend_result.c.untested_reason.is_not(None)
            )
            events = _ordered(session, c3_degradation_event, run_id)
            flags = _ordered(session, c3_static_flag, run_id)

        return StoredRun(
            run=AnalysisRun(
                run_id=row.run_id,
                system_id=row.system_id,
                status=row.status,
                started_at=row.started_at,
                finished_at=row.finished_at,
                config=row.config,
                config_hash=row.config_hash,
                code_version=row.code_version,
                lib_versions=row.lib_versions,
                releases=tuple(RunRelease.model_validate(r) for r in row.releases),
                timings=row.timings,
                reason_counts=row.reason_counts,
                error=row.error,
            ),
            outputs=RunOutputs(
                instances=tuple(
                    InstanceRecord(
                        release_id=i.release_id,
                        local_instance_id=i.local_instance_id,
                        anti_pattern_type=i.anti_pattern_type,
                        catalog=i.catalog,
                        scope=i.scope,
                        members=tuple(i.members),
                        measures=i.measures,
                    )
                    for i in instances
                ),
                trends=tuple(
                    TrendRecord(
                        scope=t.scope,
                        subject_id=t.subject_id,
                        metric=t.metric,
                        unit=t.unit,
                        worsening=t.worsening,
                        points=tuple(SeriesPointRecord.model_validate(p) for p in t.points),
                        n=t.n_points,
                        s=t.s,
                        var_s=t.var_s,
                        z=t.z,
                        tau=t.tau,
                        p_value=t.p_value,
                        q_value=t.q_value,
                        method=t.method,
                        time_axis=t.time_axis,
                        sen_slope=t.sen_slope,
                        intercept=t.intercept,
                        is_worsening=t.is_worsening,
                        is_significant=t.is_significant,
                    )
                    for t in tested
                ),
                untested=tuple(
                    UntestedRecord(
                        scope=u.scope,
                        subject_id=u.subject_id,
                        metric=u.metric,
                        reason=u.untested_reason,
                        n_points=u.n_points,
                    )
                    for u in untested
                ),
                events=tuple(DegradationEventV2.model_validate(e.payload) for e in events),
                static_flags=tuple(
                    StaticFlag(
                        release_id=f.release_id,
                        element_id=f.element_id,
                        metric=f.metric,
                        value=f.value,
                        threshold=f.threshold,
                    )
                    for f in flags
                ),
            ),
        )

    def load_artifacts(self, run_id: str) -> dict[str, Any] | None:
        with self._sessions() as session:
            stored = session.execute(
                select(c3_analysis_run.c.run_id).where(c3_analysis_run.c.run_id == run_id)
            ).one_or_none()
            if stored is None:
                return None
            rows = session.execute(
                select(c3_run_artifact.c.name, c3_run_artifact.c.payload).where(
                    c3_run_artifact.c.run_id == run_id
                )
            ).all()
        return {row.name: row.payload for row in rows}

    def _finish(self, session: Session, run: AnalysisRun) -> None:
        """Move a RUNNING run to its final state; only a RUNNING run may move."""
        if run.status is RunStatus.RUNNING:
            raise ValueError("a run can only finish as COMPLETED or FAILED")
        result = session.execute(
            update(c3_analysis_run)
            .where(
                c3_analysis_run.c.run_id == run.run_id,
                c3_analysis_run.c.status == RunStatus.RUNNING.value,
            )
            .values(**_run_values(run))
        )
        if result.rowcount != 1:  # type: ignore[attr-defined]
            raise LookupError(f"run {run.run_id} is not RUNNING")
