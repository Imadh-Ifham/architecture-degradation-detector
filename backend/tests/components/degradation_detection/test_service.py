import io
import json
import logging
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import structlog

from app.components.degradation_detection import DegradationDetectionService
from app.components.degradation_detection.config import (
    BaselineConfig,
    C3Config,
    StaticBaselineConfig,
    StaticRule,
)
from app.components.degradation_detection.models import RunResult, TrendResult
from app.components.degradation_detection.service import RUN_ARTIFACTS, new_run_id
from app.components.degradation_detection.trends import TrendService
from app.core.logging import configure_logging
from app.domain.analysis_run import RunStatus
from tests.components.degradation_detection.fakes import (
    FixedClock,
    InMemoryAnalysisRunRepository,
    InMemoryReleaseRepository,
)
from tests.components.degradation_detection.stub_pipeline import ingested_stub, stub_run

BACKEND_ROOT = Path(__file__).resolve().parents[3]
CFG = C3Config()
SYSTEM = "shopfront"

PROBE = """
import sys
from app.components.degradation_detection import DegradationDetectionService

outer = ("app.core", "app.infrastructure", "app.api", "fastapi", "sqlalchemy", "neo4j")
loaded = sorted(m for m in sys.modules if m.startswith(outer))
assert not loaded, loaded
"""


def test_component_imports_without_settings_or_databases(tmp_path: Path) -> None:
    """C3 must load with no .env and no containers, so its tests never hang on Docker.

    Runs in a fresh interpreter from an empty directory: other tests in this session import
    app.main, which would hide a leak through sys.modules.
    """
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("POSTGRES_", "NEO4J_"))}
    env["PYTHONPATH"] = str(BACKEND_ROOT)

    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr


# --- c3 run: M1 timeline -> M2 -> M3 -> M4 -> M6 export, under one analysis run (T-13) --------


@dataclass(frozen=True)
class Completed:
    service: DegradationDetectionService
    runs: InMemoryAnalysisRunRepository
    result: RunResult


@pytest.fixture(scope="module")
def completed() -> Iterator[Completed]:
    """One stub run with JSON logging on, so the run can count reason codes."""
    root = logging.getLogger()
    level, handlers = root.level, list(root.handlers)
    configure_logging("INFO", stream=io.StringIO())
    runs = InMemoryAnalysisRunRepository()
    service = DegradationDetectionService(ingested_stub(), runs, FixedClock(), CFG)
    result = service.run(SYSTEM, code_version="test-sha")
    yield Completed(service, runs, result)
    root.handlers[:] = handlers
    root.setLevel(level)
    structlog.reset_defaults()


def test_run_is_recorded_completed_with_its_provenance(completed: Completed) -> None:
    run = completed.result.stored.run
    timeline = stub_run().timeline

    assert completed.runs.runs[run.run_id] == run
    assert run.status is RunStatus.COMPLETED
    assert run.system_id == SYSTEM
    assert run.config_hash == CFG.config_hash
    assert run.config == CFG.model_dump(mode="json")
    assert run.code_version == "test-sha"
    assert {"python", "numpy", "networkx", "pydantic"} <= set(run.lib_versions)
    assert run.started_at == run.finished_at == FixedClock().now()
    assert [(r.release_id, r.gate_status) for r in run.releases] == [
        (e.release.release_id, e.release.gate_status) for e in timeline.entries
    ]
    assert set(run.timings) == {"timeline", "detection", "tracking", "trends", "events", "baseline"}
    assert all(seconds >= 0 for seconds in run.timings.values())


def test_run_counts_reason_codes(completed: Completed) -> None:
    counts = completed.result.stored.run.reason_counts
    untested = Counter(u.reason for u in stub_run().analysis.untested)

    assert untested
    for reason, n in untested.items():
        assert counts[reason] == n


def test_reasons_are_not_counted_when_logging_bypasses_the_standard_library() -> None:
    """Null stays null: without the JSON logging set up, the counter sees nothing, and an empty
    count would claim that no decision was logged."""
    structlog.reset_defaults()  # structlog's own console logger, as in a bare script
    service = DegradationDetectionService(
        ingested_stub(), InMemoryAnalysisRunRepository(), FixedClock(), CFG
    )

    result = service.run(SYSTEM, code_version="test-sha")

    assert result.stored.run.reason_counts is None


def test_run_outputs_are_the_pipeline_outputs(completed: Completed) -> None:
    out = completed.result.stored.outputs
    run = stub_run()

    assert [TrendResult.model_validate(t.model_dump()) for t in out.trends] == list(
        run.analysis.results
    )
    assert len(out.untested) == len(run.analysis.untested)
    assert [e.event_key for e in out.events] == [c.event_key for c in run.analysis.candidates]
    assert all(e.run_id == completed.result.stored.run.run_id for e in out.events)
    assert len(out.instances) == sum(len(t.occurrences) for t in run.tracking.tracks)
    assert ("legacy-auth", "fan_in") in {(f.element_id, f.metric) for f in out.static_flags}
    last = run.timeline.entries[-1].release.release_id
    assert {f.release_id for f in out.static_flags} == {last}


def test_run_is_stored_and_loads_back(completed: Completed) -> None:
    run_id = completed.result.stored.run.run_id

    assert completed.runs.load(run_id) == completed.result.stored


def test_run_stores_the_intermediate_artifacts(completed: Completed) -> None:
    artifacts = completed.runs.artifacts[completed.result.stored.run.run_id]

    assert set(artifacts) == set(RUN_ARTIFACTS)
    assert len(artifacts["series"]) == len(stub_run().tracking.series)
    assert len(artifacts["detections"]) == len(stub_run().timeline.entries)


def test_run_returns_the_files_to_write(completed: Completed) -> None:
    files = completed.result.files
    events = completed.result.stored.outputs.events

    plots = {f"plots/{e.event_id}.png" for e in events}
    assert set(files) == {"events.json", "series.csv", "report.md"} | plots
    exported = json.loads(files["events.json"])
    assert [e["event_id"] for e in exported] == [e.event_id for e in events]
    assert files["series.csv"].startswith(b"scope,")


def test_report_re_renders_a_stored_run(completed: Completed) -> None:
    run_id = completed.result.stored.run.run_id

    report = completed.service.report(run_id)

    assert report == {
        name: data
        for name, data in completed.result.files.items()
        if name == "report.md" or name.startswith("plots/")
    }


def test_report_of_an_unknown_run_fails(completed: Completed) -> None:
    with pytest.raises(LookupError, match="RUN-missing"):
        completed.service.report("RUN-missing")


def test_same_config_gives_the_same_events(completed: Completed) -> None:
    """Plan 6.4: same config hash -> same events. Only the run's own ids differ."""
    service = DegradationDetectionService(
        ingested_stub(), InMemoryAnalysisRunRepository(), FixedClock(), CFG
    )

    second = service.run(SYSTEM, code_version="test-sha")

    first_events = completed.result.stored.outputs.events
    second_events = second.stored.outputs.events
    assert second.stored.run.run_id != completed.result.stored.run.run_id
    assert {e.event_id for e in first_events}.isdisjoint(e.event_id for e in second_events)
    ids = {"run_id", "event_id"}
    assert [e.model_dump(exclude=ids) for e in second_events] == [
        e.model_dump(exclude=ids) for e in first_events
    ]
    assert second.files["series.csv"] == completed.result.files["series.csv"]


def test_default_run_ids_are_new_and_readable() -> None:
    first, second = new_run_id(), new_run_id()

    assert re.fullmatch(r"RUN-[0-9a-f]{16}", first)
    assert first != second


def test_a_failing_stage_records_a_failed_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: object, **__: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(TrendService, "analyze", boom)
    runs = InMemoryAnalysisRunRepository()
    service = DegradationDetectionService(
        ingested_stub(), runs, FixedClock(), CFG, new_run_id=lambda: "RUN-x"
    )

    with pytest.raises(RuntimeError, match="boom"):
        service.run(SYSTEM, code_version="test-sha")

    failed = runs.runs["RUN-x"]
    assert failed.status is RunStatus.FAILED
    assert failed.error == "RuntimeError: boom"
    assert failed.finished_at == FixedClock().now()
    assert "RUN-x" not in runs.outputs
    assert "tracking" in failed.timings  # the stages that finished keep their timings
    assert "trends" not in failed.timings


def test_a_system_without_releases_starts_no_run() -> None:
    runs = InMemoryAnalysisRunRepository()
    service = DegradationDetectionService(InMemoryReleaseRepository(), runs, FixedClock(), CFG)

    with pytest.raises(LookupError, match="nowhere"):
        service.run("nowhere", code_version="test-sha")

    assert runs.runs == {}


def test_a_baseline_rule_on_an_unknown_metric_fails_before_the_run() -> None:
    rules = (StaticRule(metric="fan_inn", above=1),)
    cfg = C3Config(baseline=BaselineConfig(static=StaticBaselineConfig(rules=rules)))
    runs = InMemoryAnalysisRunRepository()
    service = DegradationDetectionService(ingested_stub(), runs, FixedClock(), cfg)

    with pytest.raises(ValueError, match="fan_inn"):
        service.run(SYSTEM, code_version="test-sha")

    assert runs.runs == {}
