"""In-memory implementations of the C3 ports, for unit tests (plan: ``adapters/memory/``)."""

import copy
import datetime as dt
import json
from collections.abc import Mapping
from typing import Any

from app.domain.analysis_run import AnalysisRun, RunOutputs, RunStatus, StoredRun
from app.domain.canonical_release import CanonicalRelease


class InMemoryReleaseRepository:
    """``ReleaseRepository`` backed by a dict, keyed like the real table."""

    def __init__(self) -> None:
        self.releases: dict[tuple[str, str], CanonicalRelease] = {}
        self.raw: dict[tuple[str, str], dict[str, Any]] = {}
        self.ingested_at: dict[tuple[str, str], dt.datetime] = {}

    def find_package_hash(self, system_id: str, release_id: str) -> str | None:
        release = self.releases.get((system_id, release_id))
        return None if release is None else release.package_hash

    def add(
        self,
        release: CanonicalRelease,
        raw_payload: Mapping[str, Any],
        ingested_at: dt.datetime,
    ) -> None:
        key = (release.system_id, release.release_id)
        if key in self.releases:
            raise KeyError(f"release {key} already stored")
        self.releases[key] = release
        self.raw[key] = copy.deepcopy(dict(raw_payload))
        self.ingested_at[key] = ingested_at

    def replace(
        self,
        release: CanonicalRelease,
        raw_payload: Mapping[str, Any],
        ingested_at: dt.datetime,
    ) -> None:
        key = (release.system_id, release.release_id)
        if key not in self.releases:
            raise LookupError(f"release {key} not stored")
        del self.releases[key]
        self.add(release, raw_payload, ingested_at)

    def list_releases(self, system_id: str) -> tuple[CanonicalRelease, ...]:
        # Insertion order on purpose: the timeline must not rely on the store to sort.
        return tuple(r for (system, _), r in self.releases.items() if system == system_id)


class InMemoryAnalysisRunRepository:
    """``AnalysisRunRepository`` backed by dicts, with the same state rules as the real tables."""

    def __init__(self) -> None:
        self.runs: dict[str, AnalysisRun] = {}
        self.outputs: dict[str, RunOutputs] = {}
        self.artifacts: dict[str, dict[str, Any]] = {}

    def start(self, run: AnalysisRun) -> None:
        if run.run_id in self.runs:
            raise KeyError(f"run {run.run_id} already stored")
        if run.status is not RunStatus.RUNNING:
            raise ValueError("a run starts RUNNING")
        self.runs[run.run_id] = run

    def complete(self, run: AnalysisRun, outputs: RunOutputs, artifacts: Mapping[str, Any]) -> None:
        self._finish(run, RunStatus.COMPLETED)
        self.outputs[run.run_id] = outputs
        # Through JSON, as the JSONB column would: fails here if an artifact is not JSON.
        self.artifacts[run.run_id] = json.loads(json.dumps(dict(artifacts), allow_nan=False))

    def fail(self, run: AnalysisRun) -> None:
        self._finish(run, RunStatus.FAILED)

    def load(self, run_id: str) -> StoredRun | None:
        if run_id not in self.runs:
            return None
        return StoredRun(run=self.runs[run_id], outputs=self.outputs.get(run_id, RunOutputs()))

    def load_artifacts(self, run_id: str) -> dict[str, Any] | None:
        if run_id not in self.runs:
            return None
        return dict(self.artifacts.get(run_id, {}))

    def latest_run_id(self, system_id: str) -> str | None:
        completed = [
            run
            for run in self.runs.values()
            if run.system_id == system_id and run.status is RunStatus.COMPLETED
        ]
        if not completed:
            return None
        return max(completed, key=lambda run: (run.started_at, run.run_id)).run_id

    def _finish(self, run: AnalysisRun, status: RunStatus) -> None:
        stored = self.runs.get(run.run_id)
        if stored is None or stored.status is not RunStatus.RUNNING:
            raise KeyError(f"run {run.run_id} is not RUNNING")
        if run.status is not status:
            raise ValueError(f"expected a {status.value} run")
        self.runs[run.run_id] = run


class FixedClock:
    def __init__(self, now: dt.datetime = dt.datetime(2026, 10, 15, tzinfo=dt.UTC)) -> None:
        self.value = now

    def now(self) -> dt.datetime:
        return self.value
