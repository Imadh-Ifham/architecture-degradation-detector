"""A small hand-made stored run: three releases, one event, two static flags.

Shared by the report tests, the in-memory repository and the PostgreSQL round trip, so all three
agree on what a stored run looks like.
"""

import datetime as dt
from typing import Any

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
from app.domain.canonical_release import GateStatus
from app.domain.degradation_event import (
    AffectedMetric,
    Context,
    ContextStage,
    ContextTag,
    DegradationEventV2,
    EventProvenance,
    Scope,
    SeriesValue,
    TestMethod,
    TimeAxis,
    Window,
    Worsening,
)
from app.domain.release_package import ArchitectureStyle

RUN_ID = "RUN-0123456789abcdef"
SYSTEM = "shopfront"
STARTED = dt.datetime(2026, 10, 19, 9, 0, tzinfo=dt.UTC)
FINISHED = STARTED + dt.timedelta(seconds=2)
HASH = "sha256:" + "a" * 64
RELEASES = (
    ("v1", GateStatus.ACCEPTED),
    ("v2", GateStatus.DOWNWEIGHTED),
    ("v3", GateStatus.ACCEPTED),
)
LINEAGE = "LIN-auth@v1"
EVENT_ID = "DEG-" + "b" * 26
VALUES = (3.0, None, 9.0)


def started_run(run_id: str = RUN_ID) -> AnalysisRun:
    return AnalysisRun(
        run_id=run_id,
        system_id=SYSTEM,
        status=RunStatus.RUNNING,
        started_at=STARTED,
        config={"trend": {"alpha": 0.05}},
        config_hash=HASH,
        code_version="abc1234",
        lib_versions={"numpy": "2.5.4", "python": "3.13.1"},
        releases=tuple(
            RunRelease(
                ordinal=i,
                release_id=r,
                released_at=STARTED - dt.timedelta(days=30 * (3 - i)),
                gate_status=g,
            )
            for i, (r, g) in enumerate(RELEASES)
        ),
    )


def completed_run(run_id: str = RUN_ID) -> AnalysisRun:
    return started_run(run_id).model_copy(
        update={
            "status": RunStatus.COMPLETED,
            "finished_at": FINISHED,
            "timings": {"detection": 0.25, "trends": 1.5},
            "reason_counts": {"SERIES_TOO_SHORT": 1, "NO_WORSENING_DIRECTION": 1},
        }
    )


def failed_run(run_id: str = RUN_ID) -> AnalysisRun:
    return started_run(run_id).model_copy(
        update={"status": RunStatus.FAILED, "finished_at": FINISHED, "error": "RuntimeError: boom"}
    )


def points() -> tuple[SeriesPointRecord, ...]:
    return tuple(
        SeriesPointRecord(ordinal=i, release_id=r, value=v)
        for i, ((r, _), v) in enumerate(zip(RELEASES, VALUES, strict=True))
    )


def trend(**changes: Any) -> TrendRecord:
    fields: dict[str, Any] = {
        "scope": Scope.ELEMENT,
        "subject_id": LINEAGE,
        "metric": "fan_in",
        "unit": "elements",
        "worsening": Worsening.INCREASE,
        "points": points(),
        "n": 2,
        "s": 1,
        "tau": 1.0,
        "p_value": 0.01,
        "q_value": 0.02,
        "method": TestMethod.EXACT,
        "time_axis": TimeAxis.ORDINAL,
        "sen_slope": 3.0,
        "intercept": 3.0,
        "is_worsening": True,
        "is_significant": True,
    }
    return TrendRecord(**(fields | changes))


def event() -> DegradationEventV2:
    return DegradationEventV2(
        event_id=EVENT_ID,
        event_key="sha256:" + "c" * 64,
        run_id=RUN_ID,
        system_id=SYSTEM,
        scope=Scope.ELEMENT,
        anti_pattern_type="HubLikeElement",
        catalog="universal",
        architecture_style=ArchitectureStyle.MICROSERVICES,
        element_id="auth",
        lineage_id=LINEAGE,
        window=Window(
            start_release="v1", end_release="v3", n_releases=3, low_confidence_releases=["v2"]
        ),
        affected_metrics=[
            AffectedMetric(
                metric="fan_in",
                unit="elements",
                worsening=Worsening.INCREASE,
                n=2,
                s=1,
                tau=1.0,
                p_value=0.01,
                q_value=0.02,
                test_method=TestMethod.EXACT,
                sen_slope=3.0,
                time_axis=TimeAxis.ORDINAL,
                series=[
                    SeriesValue(release_id=r, value=v)
                    for (r, _), v in zip(RELEASES, VALUES, strict=True)
                ],
            )
        ],
        trend_strength=1.0,
        context=Context(tag=ContextTag.GENUINE, stage=ContextStage.DISABLED),
        provenance=EventProvenance(release_package_hashes=[HASH] * 3, config_hash=HASH),
    )


def outputs() -> RunOutputs:
    return RunOutputs(
        instances=(
            InstanceRecord(
                release_id="v2",
                local_instance_id="CyclicDependency:auth",
                anti_pattern_type="CyclicDependency",
                catalog="universal",
                scope=Scope.INSTANCE,
                members=("auth", "order"),
                measures={"member_count": 2.0, "internal_edge_count": None},
            ),
            InstanceRecord(
                release_id="v3",
                local_instance_id="CyclicDependency:auth",
                anti_pattern_type="CyclicDependency",
                catalog="universal",
                scope=Scope.INSTANCE,
                members=("auth", "order"),
                measures={"member_count": 2.0},
            ),
            InstanceRecord(
                release_id="v3",
                local_instance_id="HubLikeElement:auth",
                anti_pattern_type="HubLikeElement",
                catalog="universal",
                scope=Scope.ELEMENT,
                members=("auth",),
            ),
        ),
        trends=(
            trend(),
            trend(metric="fan_out", is_worsening=False, is_significant=False, q_value=0.4),
        ),
        untested=(
            UntestedRecord(
                scope=Scope.ELEMENT,
                subject_id=LINEAGE,
                metric="instability",
                reason="NO_WORSENING_DIRECTION",
                n_points=2,
            ),
            UntestedRecord(
                scope=Scope.INSTANCE,
                subject_id="AP-CyclicDependency:auth@v2",
                metric="member_count",
                reason="SERIES_TOO_SHORT",
                n_points=2,
            ),
        ),
        events=(event(),),
        static_flags=(
            StaticFlag(release_id="v3", element_id="auth", metric="fan_in", value=12, threshold=10),
            StaticFlag(
                release_id="v3", element_id="legacy", metric="size", value=12000, threshold=10000
            ),
        ),
    )


def stored_run() -> StoredRun:
    return StoredRun(run=completed_run(), outputs=outputs())


ARTIFACTS: dict[str, Any] = {"series": [{"metric": "fan_in", "points": [1, None, 3]}]}
