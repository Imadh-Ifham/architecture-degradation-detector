"""Track anti-pattern instances across releases (plan M3, instance tracking).

1. Each member is replaced by its lineage id, so a member's rename keeps the instance's identity
   and a member whose lineage broke counts as a different member.
2. Per anti-pattern type and pair of consecutive releases, instances are paired one-to-one by the
   Jaccard overlap of their lineage sets (Hungarian) and linked when the overlap reaches
   ``tracking.instance_jaccard_min`` [D-22]. A pair that is not strictly ahead of every other
   overlap in its row and column is a tie (two cycles merging, one splitting in halves): neither
   is linked. Single-element instances need no special case: their overlap is 1 or 0, so this
   is lineage matching. A system-scope type has at most one instance per release, and it is
   linked whenever it is present in both releases, whatever its members.
3. An unlinked instance starts a track. A track with no successor ends RESOLVED if the next
   release ran its detector, and UNCHECKED if it did not: absent is not the same as not checked.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import structlog
from scipy.optimize import linear_sum_assignment

from app.components.degradation_detection.config import TrackingConfig
from app.components.degradation_detection.models import (
    AntiPatternInstance,
    InstanceOccurrence,
    InstanceTrack,
    InstanceTransition,
    Lineage,
    ReleaseDetection,
    Timeline,
    TimelineEntry,
    TrackEnd,
)
from app.components.degradation_detection.tracking.models import (
    INSTANCE_MATCH_AMBIGUOUS,
    INSTANCE_TRACK_UNCHECKED,
)
from app.domain.degradation_event import Lifecycle, Scope

log = structlog.get_logger(__name__)

# Float tolerance for the overlap comparisons, so that an overlap exactly on the minimum is
# accepted as the plan states (">=") and two equal overlaps count as a tie despite rounding.
_TOLERANCE = 1e-9


def track_id(local_instance_id: str, release_id: str) -> str:
    return f"AP-{local_instance_id}@{release_id}"


@dataclass
class _Track:
    """A track being built; ``occurrences`` grows by one per release while it is linked."""

    first: AntiPatternInstance
    occurrences: list[InstanceOccurrence] = field(default_factory=list)

    @property
    def lineages(self) -> frozenset[str]:
        return frozenset(self.occurrences[-1].member_lineages)

    def close(self, end: TrackEnd, ended_at: str | None) -> InstanceTrack:
        return InstanceTrack(
            track_id=track_id(self.first.local_instance_id, self.first.release_id),
            anti_pattern_type=self.first.anti_pattern_type,
            catalog=self.first.catalog,
            scope=self.first.scope,
            occurrences=tuple(self.occurrences),
            end=end,
            ended_at=ended_at,
            lifecycle=_lifecycle(end, len(self.occurrences)),
        )


def track_instances(
    timeline: Timeline,
    detections: Sequence[ReleaseDetection],
    lineages: Sequence[Lineage],
    cfg: TrackingConfig,
) -> tuple[InstanceTrack, ...]:
    """Instance tracks in order of first appearance (then track id).

    ``detections[k]`` is M2's output for ``timeline.entries[k]``.
    """
    _check_detections(timeline, detections)
    lineage_of = {
        (member.release_id, member.element_id): lin.lineage_id
        for lin in lineages
        for member in lin.members
    }

    closed: list[InstanceTrack] = []
    current: dict[str, list[_Track]] = {}  # type -> tracks whose last occurrence is the previous
    for entry, detection in zip(timeline.entries, detections, strict=True):
        release_id = entry.release.release_id
        found: dict[str, list[AntiPatternInstance]] = defaultdict(list)
        for instance in detection.instances:
            found[instance.anti_pattern_type].append(instance)

        following: dict[str, list[_Track]] = {}
        for anti_pattern_type in sorted(current.keys() | found.keys()):
            previous = current.get(anti_pattern_type, [])
            if anti_pattern_type not in detection.detectors_run:
                for track in previous:
                    log.info(
                        INSTANCE_TRACK_UNCHECKED,
                        reason=INSTANCE_TRACK_UNCHECKED,
                        release_id=release_id,
                        anti_pattern_type=anti_pattern_type,
                        last_instance=track.occurrences[-1].local_instance_id,
                    )
                    closed.append(track.close(TrackEnd.UNCHECKED, release_id))
                continue

            instances = sorted(found[anti_pattern_type], key=lambda i: i.local_instance_id)
            occurrence_lineages = [_member_lineages(instance, lineage_of) for instance in instances]
            links = _match(
                [track.lineages for track in previous],
                [frozenset(lins) for lins in occurrence_lineages],
                instances,
                release_id,
                cfg,
            )

            linked_tracks = set()
            next_tracks: list[_Track] = []
            for j, (instance, lins) in enumerate(zip(instances, occurrence_lineages, strict=True)):
                if j in links:
                    i, jaccard = links[j]
                    track = previous[i]
                    linked_tracks.add(i)
                    transition = _transition(len(track.occurrences[-1].members), len(lins))
                else:
                    track, jaccard, transition = (
                        _Track(instance),
                        None,
                        InstanceTransition.INTRODUCED,
                    )
                track.occurrences.append(
                    InstanceOccurrence(
                        ordinal=entry.ordinal,
                        release_id=release_id,
                        local_instance_id=instance.local_instance_id,
                        members=instance.members,
                        member_lineages=lins,
                        measures=instance.measures,
                        transition=transition,
                        jaccard=jaccard,
                    )
                )
                next_tracks.append(track)
            closed.extend(
                track.close(TrackEnd.RESOLVED, release_id)
                for i, track in enumerate(previous)
                if i not in linked_tracks
            )
            following[anti_pattern_type] = next_tracks
        current = following

    closed.extend(
        track.close(TrackEnd.OPEN, None) for tracks in current.values() for track in tracks
    )
    return tuple(sorted(closed, key=lambda t: (t.occurrences[0].ordinal, t.track_id)))


def _check_detections(timeline: Timeline, detections: Sequence[ReleaseDetection]) -> None:
    if len(detections) != len(timeline.entries):
        raise ValueError("expected one detection per release on the timeline")
    for entry, detection in zip(timeline.entries, detections, strict=True):
        _check_detection(entry, detection)


def _check_detection(entry: TimelineEntry, detection: ReleaseDetection) -> None:
    release_id = entry.release.release_id
    if detection.release_id != release_id:
        raise ValueError(
            f"detection of release {detection.release_id!r} is where the timeline has "
            f"{release_id!r}"
        )
    for instance in detection.instances:
        if instance.anti_pattern_type not in detection.detectors_run:
            raise ValueError(
                f"release {release_id!r} has a {instance.anti_pattern_type} instance, but that "
                "detector did not run"
            )


def _member_lineages(
    instance: AntiPatternInstance, lineage_of: dict[tuple[str, str], str]
) -> tuple[str, ...]:
    try:
        return tuple(lineage_of[(instance.release_id, member)] for member in instance.members)
    except KeyError as exc:
        raise ValueError(
            f"member {exc.args[0][1]!r} of {instance.local_instance_id} is not an element of "
            f"release {instance.release_id!r}"
        ) from None


def _match(
    previous: Sequence[frozenset[str]],
    current: Sequence[frozenset[str]],
    instances: Sequence[AntiPatternInstance],
    release_id: str,
    cfg: TrackingConfig,
) -> dict[int, tuple[int, float]]:
    """``{current index: (previous index, jaccard)}`` for the links to make."""
    if not previous or not current:
        return {}
    overlap = np.array([[_jaccard(p, c) for c in current] for p in previous])

    if instances[0].scope is Scope.SYSTEM:
        if len(previous) > 1 or len(current) > 1:
            raise ValueError(
                f"{instances[0].anti_pattern_type} is system-scope but has more than one "
                f"instance around release {release_id!r}"
            )
        return {0: (0, float(overlap[0, 0]))}

    links: dict[int, tuple[int, float]] = {}
    rows, cols = linear_sum_assignment(overlap, maximize=True)
    for i, j in zip(rows.tolist(), cols.tolist(), strict=True):
        jaccard = float(overlap[i, j])
        if jaccard < cfg.instance_jaccard_min - _TOLERANCE:
            continue
        others = np.concatenate((np.delete(overlap[i, :], j), np.delete(overlap[:, j], i)))
        runner_up = float(others.max()) if others.size else 0.0
        if jaccard - runner_up <= _TOLERANCE:
            log.warning(
                INSTANCE_MATCH_AMBIGUOUS,
                reason=INSTANCE_MATCH_AMBIGUOUS,
                release_id=release_id,
                anti_pattern_type=instances[j].anti_pattern_type,
                instance=instances[j].local_instance_id,
                jaccard=jaccard,
                runner_up=runner_up,
            )
            continue
        links[j] = (i, jaccard)
    return links


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _transition(before: int, after: int) -> InstanceTransition:
    if after > before:
        return InstanceTransition.GREW
    if after < before:
        return InstanceTransition.SHRANK
    return InstanceTransition.PERSISTED


def _lifecycle(end: TrackEnd, age: int) -> Lifecycle | None:
    """End-of-window lifecycle as far as tracking can tell; M4 decides ``growing`` later."""
    if end is TrackEnd.RESOLVED:
        return Lifecycle.RESOLVED
    if end is TrackEnd.UNCHECKED:
        return None
    return Lifecycle.INTRODUCED if age == 1 else Lifecycle.PERSISTENT
