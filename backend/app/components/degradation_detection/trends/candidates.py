"""M4 candidate assembly: significant worsening trends -> event candidates (plan M4, step 3).

Only trends that are significant *and* worsening count. They are grouped by subject, then each
trend is given the anti-pattern type it is evidence for:

=========  ==========================================================================
Scope      Type of a trend
=========  ==========================================================================
INSTANCE   the track's type, if the instance is in the timeline's last release (track
           OPEN); a trend on an instance that has gone is not reported
ELEMENT    every anti-pattern present for the lineage in the trend's last release whose
           ``driving_metrics`` include the metric (as itself, or as a member of an instance)
SYSTEM     ``ap_count.X`` -> X; otherwise every SYSTEM-scope anti-pattern present in the
           trend's last release whose ``driving_metrics`` include it
=========  ==========================================================================

A trend with no type is ``MetricDrift`` [D-09]: one candidate per subject collects them all.
Trends of the same type on one subject are one candidate, so an event lists every metric
behind it. Nothing here names a metric or a detector: the mapping comes from the catalog M2
declares, so a new detector needs no change here.

Each candidate gets:

- **window** = span of its trends' tested (non-null) points, the releases inside it that were
  ``DOWNWEIGHTED`` [D-07], and their number;
- **instance** = the track of the anti-pattern behind it, with its members in the window's last
  release, when there is exactly one (two of one type on one subject: none is picked,
  ``CANDIDATE_INSTANCE_AMBIGUOUS``); its lifecycle turns ``persistent`` into ``growing``, the
  state M3 leaves for M4 to decide;
- ``event_key`` = hash of system, scope, subject, type, catalog and *start* release [D-18], so a
  trend that continues into later releases is the same event;
- ``trend_strength`` = max |tau|: the strength of the evidence, not severity.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence

import structlog

from app.components.degradation_detection.models import (
    DetectionCatalog,
    EventCandidate,
    InstanceOccurrence,
    InstanceTrack,
    Lineage,
    Timeline,
    TrackEnd,
    TrendResult,
    counted_type,
)
from app.components.degradation_detection.trends.models import (
    CANDIDATE_INSTANCE_AMBIGUOUS,
    TREND_ON_ENDED_INSTANCE,
)
from app.domain.canonical_release import GateStatus
from app.domain.degradation_event import Lifecycle, Scope
from app.shared.canonical_json import content_hash

log = structlog.get_logger(__name__)

# A significant worsening trend no present anti-pattern explains [D-09]. Style-neutral.
METRIC_DRIFT = "MetricDrift"
METRIC_DRIFT_CATALOG = "universal"

_SCOPE_ORDER = {Scope.ELEMENT: 0, Scope.INSTANCE: 1, Scope.SYSTEM: 2}

# A track and its occurrence in one release.
_Sighting = tuple[InstanceTrack, InstanceOccurrence]
# Release id -> the sightings that count for one subject in that release.
_Present = Callable[[str], list[_Sighting]]


def assemble_candidates(
    results: Iterable[TrendResult],
    timeline: Timeline,
    lineages: Sequence[Lineage],
    tracks: Sequence[InstanceTrack],
    catalog: DetectionCatalog,
) -> tuple[EventCandidate, ...]:
    """Event candidates sorted by scope, subject and type."""
    return _Assembler(timeline, lineages, tracks, catalog).assemble(results)


class _Assembler:
    def __init__(
        self,
        timeline: Timeline,
        lineages: Sequence[Lineage],
        tracks: Sequence[InstanceTrack],
        catalog: DetectionCatalog,
    ) -> None:
        self._timeline = timeline
        self._catalog = catalog
        self._lineages = {lineage.lineage_id: lineage for lineage in lineages}
        self._tracks = {track.track_id: track for track in tracks}
        self._releases = {entry.ordinal: entry.release for entry in timeline.entries}
        self._sightings: defaultdict[str, list[_Sighting]] = defaultdict(list)
        for track in tracks:
            for occurrence in track.occurrences:
                self._sightings[occurrence.release_id].append((track, occurrence))

    def assemble(self, results: Iterable[TrendResult]) -> tuple[EventCandidate, ...]:
        by_subject: defaultdict[tuple[Scope, str], list[TrendResult]] = defaultdict(list)
        for result in results:
            if result.is_significant and result.is_worsening:
                by_subject[result.scope, result.subject_id].append(result)

        candidates: list[EventCandidate] = []
        for (scope, subject_id), trends in by_subject.items():
            if scope is Scope.INSTANCE:
                candidates += self._instance(subject_id, trends)
            elif scope is Scope.ELEMENT:
                candidates += self._element(subject_id, trends)
            else:
                candidates += self._system(subject_id, trends)
        return tuple(
            sorted(
                candidates,
                key=lambda c: (_SCOPE_ORDER[c.scope], c.subject_id, c.anti_pattern_type),
            )
        )

    # --- per scope ----------------------------------------------------------------------

    def _instance(self, track_id: str, trends: list[TrendResult]) -> list[EventCandidate]:
        track = self._track(track_id)
        if track.end is not TrackEnd.OPEN:
            log.info(
                TREND_ON_ENDED_INSTANCE,
                reason=TREND_ON_ENDED_INSTANCE,
                track_id=track_id,
                end=track.end.value,
                metrics=sorted(t.metric for t in trends),
            )
            return []
        return [
            self._candidate(
                Scope.INSTANCE,
                track_id,
                track.anti_pattern_type,
                track.catalog,
                trends,
                instance=(track, track.occurrences[-1]),
            )
        ]

    def _element(self, lineage_id: str, trends: list[TrendResult]) -> list[EventCandidate]:
        lineage = self._lineage(lineage_id)

        def present(release_id: str) -> list[_Sighting]:
            return [
                (track, o)
                for track, o in self._sightings[release_id]
                if lineage_id in o.member_lineages
            ]

        candidates = []
        for anti_pattern_type, typed in self._typed(trends, present, counts=False).items():
            end = self._window_end(typed)
            [element_id] = [m.element_id for m in lineage.members if m.release_id == end]
            candidates.append(
                self._typed_candidate(
                    Scope.ELEMENT,
                    lineage_id,
                    anti_pattern_type,
                    typed,
                    present(end),
                    element_id=element_id,
                )
            )
        return candidates

    def _system(self, system_id: str, trends: list[TrendResult]) -> list[EventCandidate]:
        def present(release_id: str) -> list[_Sighting]:
            return [(t, o) for t, o in self._sightings[release_id] if t.scope is Scope.SYSTEM]

        return [
            self._typed_candidate(
                Scope.SYSTEM,
                system_id,
                anti_pattern_type,
                typed,
                present(self._window_end(typed)),
            )
            for anti_pattern_type, typed in self._typed(trends, present, counts=True).items()
        ]

    # --- mapping trends to anti-pattern types -------------------------------------------

    def _typed(
        self,
        trends: list[TrendResult],
        present: _Present,
        *,
        counts: bool,
    ) -> dict[str, list[TrendResult]]:
        """Anti-pattern type -> the trends that are evidence for it (MetricDrift for none)."""
        typed: defaultdict[str, list[TrendResult]] = defaultdict(list)
        for trend in trends:
            types = self._types_of(trend, present, counts=counts)
            for anti_pattern_type in types or {METRIC_DRIFT}:
                typed[anti_pattern_type].append(trend)
        return dict(typed)

    def _types_of(self, trend: TrendResult, present: _Present, *, counts: bool) -> set[str]:
        counted = counted_type(trend.metric) if counts else None
        if counted is not None:
            return {counted}
        last = trend.tested_points[-1].release_id
        return {
            track.anti_pattern_type
            for track, _ in present(last)
            if trend.metric in self._catalog.detector(track.anti_pattern_type).driving_metrics
        }

    # --- building a candidate -----------------------------------------------------------

    def _typed_candidate(
        self,
        scope: Scope,
        subject_id: str,
        anti_pattern_type: str,
        trends: list[TrendResult],
        present_at_end: list[_Sighting],
        element_id: str | None = None,
    ) -> EventCandidate:
        if anti_pattern_type == METRIC_DRIFT:
            catalog, instance = METRIC_DRIFT_CATALOG, None
        else:
            catalog = self._catalog.detector(anti_pattern_type).catalog
            same_type = [s for s in present_at_end if s[0].anti_pattern_type == anti_pattern_type]
            instance = same_type[0] if len(same_type) == 1 else None
            if len(same_type) > 1:
                log.info(
                    CANDIDATE_INSTANCE_AMBIGUOUS,
                    reason=CANDIDATE_INSTANCE_AMBIGUOUS,
                    subject_id=subject_id,
                    anti_pattern_type=anti_pattern_type,
                    track_ids=sorted(track.track_id for track, _ in same_type),
                )
        return self._candidate(
            scope,
            subject_id,
            anti_pattern_type,
            catalog,
            trends,
            instance=instance,
            element_id=element_id,
            lineage_id=subject_id if scope is Scope.ELEMENT else None,
        )

    def _candidate(
        self,
        scope: Scope,
        subject_id: str,
        anti_pattern_type: str,
        catalog: str,
        trends: list[TrendResult],
        *,
        instance: _Sighting | None,
        element_id: str | None = None,
        lineage_id: str | None = None,
    ) -> EventCandidate:
        start, end = self._window(trends)
        start_release = self._releases[start].release_id
        track = instance[0] if instance else None
        return EventCandidate(
            event_key=content_hash(
                {
                    "system_id": self._timeline.system_id,
                    "scope": scope.value,
                    "subject_id": subject_id,
                    "anti_pattern_type": anti_pattern_type,
                    "catalog": catalog,
                    "start_release": start_release,
                }
            ),
            scope=scope,
            subject_id=subject_id,
            anti_pattern_type=anti_pattern_type,
            catalog=catalog,
            element_id=element_id,
            lineage_id=lineage_id,
            instance_id=track.track_id if track else None,
            members=instance[1].members if instance else (),
            lifecycle=_lifecycle(track) if track else None,
            start_release=start_release,
            end_release=self._releases[end].release_id,
            n_releases=end - start + 1,
            low_confidence_releases=tuple(
                self._releases[k].release_id
                for k in range(start, end + 1)
                if self._releases[k].gate_status is GateStatus.DOWNWEIGHTED
            ),
            trends=tuple(sorted(trends, key=lambda t: t.metric)),
            trend_strength=max(abs(t.tau) for t in trends),
        )

    @staticmethod
    def _window(trends: Sequence[TrendResult]) -> tuple[int, int]:
        """First and last ordinal with a tested point in any of the trends."""
        ordinals = [p.ordinal for t in trends for p in t.tested_points]
        return min(ordinals), max(ordinals)

    def _window_end(self, trends: Sequence[TrendResult]) -> str:
        return self._releases[self._window(trends)[1]].release_id

    def _track(self, track_id: str) -> InstanceTrack:
        try:
            return self._tracks[track_id]
        except KeyError:
            raise KeyError(f"trend on unknown instance track {track_id!r}") from None

    def _lineage(self, lineage_id: str) -> Lineage:
        try:
            return self._lineages[lineage_id]
        except KeyError:
            raise KeyError(f"trend on unknown lineage {lineage_id!r}") from None


def _lifecycle(track: InstanceTrack) -> Lifecycle | None:
    """M3's lifecycle, with ``persistent`` -> ``growing``: M4 found the instance worsening."""
    return Lifecycle.GROWING if track.lifecycle is Lifecycle.PERSISTENT else track.lifecycle
