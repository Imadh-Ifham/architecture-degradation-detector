"""Protocols for everything C3 needs from outside the component.

Implemented under ``app/infrastructure/``; unit tests use in-memory fakes from ``tests/``.
Types that cross a port live in ``app/domain/``, because infrastructure may not import
components.
"""

import datetime as dt
from collections.abc import Mapping
from typing import Any, Protocol

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
