"""M1 steps 7-9: the timeline of one system (pure).

The timeline is recomputed from the stored releases at the start of every run, never stored:

- releases are ordered by ``released_at``, never by tag name (as text ``v1.10.0`` < ``v1.9.0``);
  equal timestamps fall back to the semantic version, then to the id, so the order is total;
- only the main release line counts (``ingest.release_line_regex``) [D-06]: a back-port
  released between two main releases would put a point from another branch into the series;
- EXCLUDED releases stay in the store but not on the timeline [D-07];
- ordinals are positions on this timeline, so they change when a release is added or excluded
  and are never used as identity.

Intents are deduplicated here rather than at ingest, so ``first_seen_release`` and
``last_seen_release`` follow the timeline even when packages were ingested out of order.
"""

import re
from collections.abc import Iterable

import structlog

from app.components.degradation_detection.config import IngestConfig
from app.components.degradation_detection.ingestion.models import (
    ARCHITECTURE_STYLE_CHANGED,
    GRANULARITY_CHANGED,
    RELEASE_EXCLUDED,
    RELEASE_OFF_MAIN_LINE,
)
from app.components.degradation_detection.models import IntentRecord, Timeline, TimelineEntry
from app.domain.canonical_release import CanonicalRelease, GateStatus, IntentEntry

log = structlog.get_logger(__name__)

_SEMVER = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


def _semver_key(release_id: str) -> tuple[int, tuple[int, ...]]:
    """Semantic versions first, in numeric order; anything else after them."""
    match = _SEMVER.fullmatch(release_id)
    if match is None:
        return (1, ())
    return (0, tuple(int(part) for part in match.groups()))


def _order_key(release: CanonicalRelease) -> tuple[object, ...]:
    return (release.released_at, _semver_key(release.release_id), release.release_id)


def _on_timeline(release: CanonicalRelease, main_line: re.Pattern[str]) -> bool:
    if main_line.search(release.release_id) is None:
        log.info(
            RELEASE_OFF_MAIN_LINE,
            reason=RELEASE_OFF_MAIN_LINE,
            system_id=release.system_id,
            release_id=release.release_id,
        )
        return False
    if release.gate_status is GateStatus.EXCLUDED:
        log.info(
            RELEASE_EXCLUDED,
            reason=RELEASE_EXCLUDED,
            system_id=release.system_id,
            release_id=release.release_id,
            validation_confidence=release.validation_confidence,
        )
        return False
    return True


def _log_drift(releases: list[CanonicalRelease]) -> None:
    """Metrics are not comparable across a change of style or granularity; warn, don't stop."""
    for before, after in zip(releases, releases[1:], strict=False):
        if after.architecture_style != before.architecture_style:
            log.warning(
                ARCHITECTURE_STYLE_CHANGED,
                reason=ARCHITECTURE_STYLE_CHANGED,
                system_id=after.system_id,
                release_id=after.release_id,
                previous=before.architecture_style.value,
                current=after.architecture_style.value,
            )
        if after.granularity != before.granularity:
            log.warning(
                GRANULARITY_CHANGED,
                reason=GRANULARITY_CHANGED,
                system_id=after.system_id,
                release_id=after.release_id,
                previous=before.granularity,
                current=after.granularity,
            )


def _dedupe_intents(releases: list[CanonicalRelease]) -> tuple[IntentRecord, ...]:
    """One record per ``intent_id``; the latest release that states an intent has the last word."""
    latest: dict[str, IntentEntry] = {}
    first: dict[str, str] = {}
    last: dict[str, str] = {}
    for release in releases:  # timeline order
        for intent in release.intent:
            first.setdefault(intent.intent_id, release.release_id)
            last[intent.intent_id] = release.release_id
            latest[intent.intent_id] = intent
    return tuple(
        IntentRecord(
            intent=latest[intent_id],
            first_seen_release=first[intent_id],
            last_seen_release=last[intent_id],
        )
        for intent_id in sorted(latest)
    )


def timeline(system_id: str, releases: Iterable[CanonicalRelease], cfg: IngestConfig) -> Timeline:
    main_line = re.compile(cfg.release_line_regex)
    ordered = [r for r in sorted(releases, key=_order_key) if _on_timeline(r, main_line)]
    _log_drift(ordered)
    return Timeline(
        system_id=system_id,
        entries=tuple(
            TimelineEntry(ordinal=ordinal, release=release)
            for ordinal, release in enumerate(ordered)
        ),
        intents=_dedupe_intents(ordered),
    )
