"""Protocols for everything C3 needs from outside the component.

Implemented under ``app/infrastructure/``; unit tests use in-memory fakes from ``tests/``.
Types that cross a port live in ``app/domain/``, because infrastructure may not import
components.
"""

import datetime as dt
from collections.abc import Mapping
from typing import Any, Protocol

from app.domain.analysis_run import AnalysisRun, RunOutputs, StoredRun
from app.domain.canonical_release import CanonicalRelease


class Clock(Protocol):
    def now(self) -> dt.datetime:
        """The current time, timezone-aware."""
        ...


class ReleaseRepository(Protocol):
    """Ingested releases, keyed by (``system_id``, ``release_id``). Written only by M1."""

    def find_package_hash(self, system_id: str, release_id: str) -> str | None:
        """The stored ``package_hash`` of a release, or None if it was never ingested."""
        ...

    def add(
        self,
        release: CanonicalRelease,
        raw_payload: Mapping[str, Any],
        ingested_at: dt.datetime,
    ) -> None:
        """Store one release and the JSON it was built from, in a single transaction.

        Fails if the release is already stored: replacing a release is not supported yet.
        """
        ...

    def list_releases(self, system_id: str) -> tuple[CanonicalRelease, ...]:
        """Every stored release of one system, EXCLUDED ones included, in no particular order."""
        ...


class AnalysisRunRepository(Protocol):
    """Analysis runs and their outputs, keyed by ``run_id``. Written only by the component service.

    A run is stored when it starts (RUNNING) and finished exactly once, as COMPLETED with all its
    outputs or as FAILED with none.
    """

    def start(self, run: AnalysisRun) -> None:
        """Store a RUNNING run. Fails if the ``run_id`` is already stored."""
        ...

    def complete(self, run: AnalysisRun, outputs: RunOutputs, artifacts: Mapping[str, Any]) -> None:
        """Finish a RUNNING run as COMPLETED and store its outputs and JSON artifacts, in a
        single transaction. Raises ``LookupError`` if no such run is RUNNING."""
        ...

    def fail(self, run: AnalysisRun) -> None:
        """Finish a RUNNING run as FAILED. Raises ``LookupError`` if no such run is RUNNING."""
        ...

    def load(self, run_id: str) -> StoredRun | None:
        """A stored run and its outputs, or None if the run was never stored."""
        ...
