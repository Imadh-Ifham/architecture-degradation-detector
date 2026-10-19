"""Build the series M4 tests (plan M3, series builder): one table, three scopes.

=========  ===============  ===================================================
Scope      Subject          Points
=========  ===============  ===================================================
ELEMENT    lineage id       element observations of the lineage's members
INSTANCE   track id         ``measures`` of the track's occurrences
SYSTEM     system id        system observations (graph metrics, anti-pattern counts)
=========  ===============  ===================================================

Rules:

- **Null stays null.** An undefined value, or a metric missing from a release where its subject
  exists, is a null point in its place: never 0, never dropped. The ordinal is M4's time axis.
- A series starts when its subject first exists and has a point for every release it exists in.
  Lineages and tracks are consecutive by construction, so ELEMENT and INSTANCE series have no
  holes, and a rename does not split a series (it follows the lineage, not the element id).
- **Only INSTANCE-scope tracks get series** (owner decision). An ELEMENT-scope instance is one
  element, so its trend is its lineage's ELEMENT series (OversizedElement's measure *is*
  ``size_rz``), and BigBallOfMud's measures are the system metrics. A copy would be tested twice:
  two events for one change, and a larger Benjamini-Hochberg family.
- **Anti-pattern counts are compared only over releases that ran the same detectors**
  ("style-specific series only over contiguous same-style releases"). ``ap_count.X`` needs X to
  have run; ``ap_involvement_share`` needs the same set of detectors. Where that changes the
  series is cut and only the last measured stretch is kept (``SERIES_DETECTOR_GAP``, owner
  decision): break rather than join two separate stretches into one trend.
"""

import itertools
from collections import defaultdict
from collections.abc import Iterator, Sequence

import structlog

from app.components.degradation_detection.models import (
    AP_INVOLVEMENT_SHARE,
    InstanceTrack,
    Lineage,
    ReleaseDetection,
    Series,
    SeriesPoint,
    Timeline,
    counted_type,
)
from app.components.degradation_detection.tracking.models import SERIES_DETECTOR_GAP
from app.domain.degradation_event import Scope

log = structlog.get_logger(__name__)

_SCOPE_ORDER = {Scope.ELEMENT: 0, Scope.INSTANCE: 1, Scope.SYSTEM: 2}

# (release id, element id or None for the system, metric) -> observed value
_Observed = dict[tuple[str, str | None, str], float | None]


def build_series(
    timeline: Timeline,
    detections: Sequence[ReleaseDetection],
    lineages: Sequence[Lineage],
    tracks: Sequence[InstanceTrack],
) -> tuple[Series, ...]:
    """Every series of the timeline, by scope (ELEMENT, INSTANCE, SYSTEM), subject and metric.

    ``detections[k]`` is M2's output for ``timeline.entries[k]``.
    """
    observed = _observed(timeline, detections)
    series = [
        *_element_series(lineages, observed),
        *_instance_series(tracks),
        *_system_series(timeline, detections, observed),
    ]
    return tuple(sorted(series, key=lambda s: (_SCOPE_ORDER[s.scope], s.subject_id, s.metric)))


def _observed(timeline: Timeline, detections: Sequence[ReleaseDetection]) -> _Observed:
    if len(detections) != len(timeline.entries):
        raise ValueError("expected one detection per release on the timeline")
    observed: _Observed = {}
    for entry, detection in zip(timeline.entries, detections, strict=True):
        release_id = entry.release.release_id
        if detection.release_id != release_id:
            raise ValueError(
                f"detection of release {detection.release_id!r} is where the timeline has "
                f"{release_id!r}"
            )
        elements = {element.element_id for element in entry.release.elements}
        for o in detection.observations:
            if o.release_id != release_id:
                raise ValueError(
                    f"observation of release {o.release_id!r} in the detection of {release_id!r}"
                )
            if o.element_id is not None and o.element_id not in elements:
                raise ValueError(
                    f"{o.metric} observed for {o.element_id!r}, which is not an element of "
                    f"release {release_id!r}"
                )
            key = (release_id, o.element_id, o.metric)
            if key in observed:
                subject = o.element_id or "the system"
                raise ValueError(f"{o.metric} of {subject} observed twice in {release_id!r}")
            observed[key] = o.value
    return observed


def _element_series(lineages: Sequence[Lineage], observed: _Observed) -> Iterator[Series]:
    metrics_of: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    for release_id, element_id, metric in observed:
        if element_id is not None:
            metrics_of[release_id, element_id].add(metric)
    for lineage in lineages:
        metrics = set().union(
            *(metrics_of.get((m.release_id, m.element_id), ()) for m in lineage.members)
        )
        for metric in metrics:
            yield Series(
                scope=Scope.ELEMENT,
                subject_id=lineage.lineage_id,
                metric=metric,
                points=tuple(
                    SeriesPoint(
                        ordinal=m.ordinal,
                        release_id=m.release_id,
                        value=observed.get((m.release_id, m.element_id, metric)),
                    )
                    for m in lineage.members
                ),
            )


def _instance_series(tracks: Sequence[InstanceTrack]) -> Iterator[Series]:
    for track in tracks:
        if track.scope is not Scope.INSTANCE:
            continue
        for metric in {name for o in track.occurrences for name in o.measures}:
            yield Series(
                scope=Scope.INSTANCE,
                subject_id=track.track_id,
                metric=metric,
                points=tuple(
                    SeriesPoint(
                        ordinal=o.ordinal, release_id=o.release_id, value=o.measures.get(metric)
                    )
                    for o in track.occurrences
                ),
            )


def _system_series(
    timeline: Timeline, detections: Sequence[ReleaseDetection], observed: _Observed
) -> Iterator[Series]:
    for metric in {metric for _, element_id, metric in observed if element_id is None}:
        points = [
            SeriesPoint(
                ordinal=entry.ordinal,
                release_id=entry.release.release_id,
                value=observed.get((entry.release.release_id, None, metric)),
            )
            for entry in timeline.entries
        ]
        ran = [_detectors_behind(metric, d.detectors_run) for d in detections]
        kept = _last_measured_stretch(timeline.system_id, metric, points, ran)
        if kept:
            yield Series(
                scope=Scope.SYSTEM, subject_id=timeline.system_id, metric=metric, points=kept
            )


def _detectors_behind(metric: str, detectors_run: Sequence[str]) -> frozenset[str] | None:
    """The detectors that ran and that ``metric`` counts; None when it counts no detector."""
    counted = counted_type(metric)
    if counted is not None:
        return frozenset({counted} & set(detectors_run))
    if metric == AP_INVOLVEMENT_SHARE:
        return frozenset(detectors_run)
    return None


def _last_measured_stretch(
    system_id: str,
    metric: str,
    points: Sequence[SeriesPoint],
    ran: Sequence[frozenset[str] | None],
) -> tuple[SeriesPoint, ...]:
    """The points of the last stretch of releases that ran the same (non-empty) detectors.

    A graph metric (``ran`` all None) keeps every point. A stretch where none of the metric's
    detectors ran holds only nulls, so it is dropped without a log: nothing measured is lost.
    """
    stretches = [
        (detectors, [point for point, _ in group])
        for detectors, group in itertools.groupby(zip(points, ran, strict=True), lambda p: p[1])
    ]
    measured = [group for detectors, group in stretches if detectors is None or detectors]
    if not measured:
        return ()
    dropped = sum(len(group) for group in measured[:-1])
    if dropped:
        log.info(
            SERIES_DETECTOR_GAP,
            reason=SERIES_DETECTOR_GAP,
            system_id=system_id,
            metric=metric,
            points_dropped=dropped,
            kept_from=measured[-1][0].release_id,
        )
    return tuple(measured[-1])
