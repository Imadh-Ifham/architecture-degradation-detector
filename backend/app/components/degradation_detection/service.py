"""C3 orchestration: the only way into the degradation detection component.

Pipeline (docs/implementation-plan.md Section 2.2): ingestion -> detection -> tracking ->
trends -> events. Subcomponents never import each other; this service passes artifacts
between them.

``run`` analyses every release on one system's timeline under one analysis run (plan T-13):

1. M1 timeline of the ingested releases (ingesting is a separate step, ``IngestService``);
2. M2 metrics and anti-pattern instances per release;
3. M3 lineages, instance tracks and series;
4. M4 trends and event candidates;
5. M6 export to ``DegradationEventV2`` (context disabled in PP1: the trend-only baseline);
6. the static-threshold baseline on the last release, for comparison only.

The run is stored RUNNING before step 2 and finished exactly once: COMPLETED with every output
in one transaction, or FAILED with the error and no outputs. It records the config and its
hash, the code and library versions, stage timings and how often each reason code was logged,
so any number in a report can be traced back to the run that produced it.
"""

import importlib.metadata
import platform
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import structlog
from pydantic import BaseModel

from app.components.degradation_detection.baselines import StaticBaselineService
from app.components.degradation_detection.config import C3Config
from app.components.degradation_detection.detection import DetectionService
from app.components.degradation_detection.events import EventService
from app.components.degradation_detection.ingestion import IngestService
from app.components.degradation_detection.models import (
    DetectionCatalog,
    MetricLevel,
    RunResult,
    Timeline,
)
from app.components.degradation_detection.ports import (
    AnalysisRunRepository,
    Clock,
    ReleaseRepository,
)
from app.components.degradation_detection.report import ReportService
from app.components.degradation_detection.tracking import TrackingService
from app.components.degradation_detection.tracking.series_csv import series_csv
from app.components.degradation_detection.trends import TrendService
from app.domain.analysis_run import (
    AnalysisRun,
    InstanceRecord,
    RunOutputs,
    RunRelease,
    RunStatus,
    StoredRun,
    TrendRecord,
    UntestedRecord,
)
from app.shared.reason_counter import count_reasons

log = structlog.get_logger()

# Libraries whose version can change a number in the output; recorded on every run.
LIBRARIES = ("jsonschema", "matplotlib", "networkx", "numpy", "pydantic")
# Intermediate results stored as JSON beside the run, for audit and evaluation (T-14).
RUN_ARTIFACTS = (
    "catalog",
    "detections",
    "lineages",
    "lineage_events",
    "alignment_decisions",
    "tracks",
    "series",
)


def new_run_id() -> str:
    return f"RUN-{uuid.uuid4().hex[:16]}"


def lib_versions() -> dict[str, str]:
    versions = {name: importlib.metadata.version(name) for name in LIBRARIES}
    versions["python"] = platform.python_version()
    return versions


@contextmanager
def _timed(timings: dict[str, float], stage: str) -> Iterator[None]:
    """Record a stage's wall time, only if it finishes."""
    start = time.perf_counter()
    yield
    timings[stage] = round(time.perf_counter() - start, 6)


def _reasons_observable() -> bool:
    """True when structlog hands its records to the standard library, where the reason counter
    listens (``app/core/logging.py``). A bare script logs through structlog's own console
    logger instead; its reasons cannot be counted, and the run stores None, not an empty count.
    """
    return isinstance(structlog.get_config()["logger_factory"], structlog.stdlib.LoggerFactory)


def _json(items: Sequence[BaseModel]) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in items]


class DegradationDetectionService:
    def __init__(
        self,
        releases: ReleaseRepository,
        runs: AnalysisRunRepository,
        clock: Clock,
        cfg: C3Config,
        *,
        new_run_id: Callable[[], str] = new_run_id,
    ) -> None:
        self._releases = releases
        self._runs = runs
        self._clock = clock
        self._cfg = cfg
        self._new_run_id = new_run_id

    def run(self, system_id: str, *, code_version: str) -> RunResult:
        """Analyse every release on one system's timeline and store the run.

        ``code_version`` is the git commit of the running code (the entry point knows it).
        Raises ``LookupError`` if the system has no release on its timeline (no run is
        started) and re-raises whatever made a started run fail, after storing it FAILED.
        """
        catalog = DetectionService(self._cfg).describe()
        self._check_baseline_rules(catalog)
        started_at = self._clock.now()
        timings: dict[str, float] = {}
        counted = _reasons_observable()

        with count_reasons() as reasons:
            with _timed(timings, "timeline"):
                timeline = IngestService(self._releases, self._clock, self._cfg).timeline(system_id)
            if not timeline.entries:
                raise LookupError(f"no releases on the timeline of system {system_id!r}")

            run = AnalysisRun(
                run_id=self._new_run_id(),
                system_id=system_id,
                status=RunStatus.RUNNING,
                started_at=started_at,
                config=self._cfg.model_dump(mode="json"),
                config_hash=self._cfg.config_hash,
                code_version=code_version,
                lib_versions=lib_versions(),
                releases=tuple(
                    RunRelease(
                        ordinal=entry.ordinal,
                        release_id=entry.release.release_id,
                        released_at=entry.release.released_at,
                        gate_status=entry.release.gate_status,
                    )
                    for entry in timeline.entries
                ),
            )
            self._runs.start(run)
            log.info("RUN_STARTED", run_id=run.run_id, system_id=system_id)
            try:
                outputs, artifacts, files = self._analyse(timeline, run.run_id, catalog, timings)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                log.error("RUN_FAILED", run_id=run.run_id, error=error)
                self._runs.fail(
                    self._finished(
                        run, RunStatus.FAILED, timings, dict(reasons) if counted else None, error
                    )
                )
                raise

        done = self._finished(run, RunStatus.COMPLETED, timings, dict(reasons) if counted else None)
        self._runs.complete(done, outputs, artifacts)
        log.info("RUN_COMPLETED", run_id=run.run_id, events=len(outputs.events))
        stored = StoredRun(run=done, outputs=outputs)
        return RunResult(stored=stored, files=files | ReportService().render(stored))

    def report(self, run_id: str) -> dict[str, bytes]:
        """``report.md`` and the event plots of a stored run, by path. Raises ``LookupError``
        if the run was never stored."""
        stored = self._runs.load(run_id)
        if stored is None:
            raise LookupError(f"no analysis run {run_id!r}")
        return ReportService().render(stored)

    def _analyse(
        self,
        timeline: Timeline,
        run_id: str,
        catalog: DetectionCatalog,
        timings: dict[str, float],
    ) -> tuple[RunOutputs, dict[str, Any], dict[str, bytes]]:
        cfg = self._cfg
        detection = DetectionService(cfg)
        with _timed(timings, "detection"):
            detections = [detection.detect(entry.release) for entry in timeline.entries]
        with _timed(timings, "tracking"):
            tracking = TrackingService(cfg).track(timeline, detections)
        with _timed(timings, "trends"):
            analysis = TrendService(cfg).analyze(
                timeline, tracking.series, tracking.lineages, tracking.tracks, catalog
            )
        with _timed(timings, "events"):
            export = EventService(cfg).emit(analysis.candidates, timeline, run_id)
        with _timed(timings, "baseline"):
            flags = StaticBaselineService(cfg).flag(detections[-1])

        # Internal models -> stored records, field by field (extra="forbid" on both sides, so a
        # field added to one and not the other fails here instead of being dropped).
        outputs = RunOutputs(
            instances=tuple(
                InstanceRecord.model_validate(i.model_dump())
                for d in detections
                for i in d.instances
            ),
            trends=tuple(TrendRecord.model_validate(r.model_dump()) for r in analysis.results),
            untested=tuple(
                UntestedRecord.model_validate(u.model_dump()) for u in analysis.untested
            ),
            events=export.events,
            static_flags=flags,
        )
        artifacts: dict[str, Any] = {
            "catalog": catalog.model_dump(mode="json"),
            "detections": _json(detections),
            "lineages": _json(tracking.lineages),
            "lineage_events": _json(tracking.events),
            "alignment_decisions": _json(tracking.decisions),
            "tracks": _json(tracking.tracks),
            "series": _json(tracking.series),
        }
        files = {
            "events.json": export.text.encode("utf-8"),
            "series.csv": series_csv(tracking.series).encode("utf-8"),
        }
        return outputs, artifacts, files

    def _check_baseline_rules(self, catalog: DetectionCatalog) -> None:
        """A static rule must name an element metric M2 measures, or it would silently flag
        nothing."""
        measured = {m.name for m in catalog.metrics if m.level is MetricLevel.ELEMENT}
        unknown = [r.metric for r in self._cfg.baseline.static.rules if r.metric not in measured]
        if unknown:
            raise ValueError(f"baseline.static rules name unknown element metrics: {unknown}")

    def _finished(
        self,
        run: AnalysisRun,
        status: RunStatus,
        timings: dict[str, float],
        reasons: dict[str, int] | None,
        error: str | None = None,
    ) -> AnalysisRun:
        # Validated again (model_copy would not), so a finished run always satisfies its rules.
        return AnalysisRun.model_validate(
            run.model_dump()
            | {
                "status": status,
                "finished_at": self._clock.now(),
                "timings": dict(timings),
                "reason_counts": reasons,
                "error": error,
            }
        )
