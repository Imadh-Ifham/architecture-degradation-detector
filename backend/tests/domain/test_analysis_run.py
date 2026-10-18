"""Analysis-run records: what C3 stores for one run, through the AnalysisRunRepository port."""

import datetime as dt
from typing import Any

import pytest
from pydantic import ValidationError

from app.domain.analysis_run import (
    AnalysisRun,
    RunRelease,
    RunStatus,
    SeriesPointRecord,
    TrendRecord,
)
from app.domain.canonical_release import GateStatus
from app.domain.degradation_event import Scope, TestMethod, TimeAxis, Worsening

STARTED = dt.datetime(2026, 10, 19, 9, 0, tzinfo=dt.UTC)
FINISHED = STARTED + dt.timedelta(seconds=3)


def run(**changes: Any) -> AnalysisRun:
    fields: dict[str, Any] = {
        "run_id": "RUN-1",
        "system_id": "shopfront",
        "status": RunStatus.RUNNING,
        "started_at": STARTED,
        "config": {"trend": {"alpha": 0.05}},
        "config_hash": "sha256:" + "0" * 64,
        "code_version": "abc1234",
        "lib_versions": {"numpy": "2.5.4"},
        "releases": (
            RunRelease(
                ordinal=0,
                release_id="v1.0.0",
                released_at=STARTED,
                gate_status=GateStatus.ACCEPTED,
            ),
        ),
    }
    return AnalysisRun(**(fields | changes))


def test_a_running_run_has_no_end_and_no_error() -> None:
    started = run()

    assert started.finished_at is None
    assert started.error is None
    assert started.timings == {}
    assert started.reason_counts is None  # not counted (yet)


def test_a_completed_run_has_an_end() -> None:
    done = run(status=RunStatus.COMPLETED, finished_at=FINISHED)

    assert done.finished_at == FINISHED


@pytest.mark.parametrize(
    "changes",
    [
        {"finished_at": FINISHED},  # RUNNING with an end
        {"status": RunStatus.COMPLETED},  # finished without an end
        {"status": RunStatus.FAILED, "finished_at": FINISHED},  # failed without an error
        {"status": RunStatus.COMPLETED, "finished_at": FINISHED, "error": "x"},  # error on success
        {"started_at": dt.datetime(2026, 10, 19)},  # naive time
        {"config_hash": "md5:1"},
    ],
    ids=[
        "running-with-end",
        "completed-without-end",
        "failed-without-error",
        "completed-with-error",
        "naive-start",
        "bad-hash",
    ],
)
def test_inconsistent_runs_are_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        run(**changes)


def test_a_failed_run_carries_its_error() -> None:
    failed = run(status=RunStatus.FAILED, finished_at=FINISHED, error="RuntimeError: boom")

    assert failed.error == "RuntimeError: boom"


def test_records_are_strict_and_immutable() -> None:
    """C3 writes these itself, so an unknown field is our own mistake."""
    with pytest.raises(ValidationError):
        SeriesPointRecord(ordinal=0, release_id="v1", value=1.0, extra=1)  # type: ignore[call-arg]

    point = SeriesPointRecord(ordinal=0, release_id="v1", value=None)
    with pytest.raises(ValidationError):
        point.value = 2.0  # type: ignore[misc]


def test_trend_record_keeps_nulls_in_its_points() -> None:
    record = TrendRecord(
        scope=Scope.ELEMENT,
        subject_id="LIN-a@v1",
        metric="fan_in",
        unit="edges",
        worsening=Worsening.INCREASE,
        points=(
            SeriesPointRecord(ordinal=0, release_id="v1", value=1.0),
            SeriesPointRecord(ordinal=1, release_id="v2", value=None),
        ),
        n=8,
        s=20,
        tau=0.7,
        p_value=0.01,
        q_value=0.02,
        method=TestMethod.EXACT,
        time_axis=TimeAxis.ORDINAL,
        sen_slope=0.5,
        intercept=1.0,
        is_worsening=True,
        is_significant=True,
    )

    assert record.points[1].value is None
    assert record.var_s is None and record.z is None
