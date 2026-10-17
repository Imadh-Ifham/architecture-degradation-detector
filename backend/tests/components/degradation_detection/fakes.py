"""In-memory implementations of the C3 ports, for unit tests (plan: ``adapters/memory/``)."""

import copy
import datetime as dt
from collections.abc import Mapping
from typing import Any

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

    def list_releases(self, system_id: str) -> tuple[CanonicalRelease, ...]:
        # Insertion order on purpose: the timeline must not rely on the store to sort.
        return tuple(r for (system, _), r in self.releases.items() if system == system_id)


class FixedClock:
    def __init__(self, now: dt.datetime = dt.datetime(2026, 10, 15, tzinfo=dt.UTC)) -> None:
        self.value = now

    def now(self) -> dt.datetime:
        return self.value
