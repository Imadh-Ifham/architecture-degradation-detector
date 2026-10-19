"""Small timelines for the M3 tests: releases built from element specs and an edge list, and
the M2 detections that go with them."""

import datetime as dt
from collections.abc import Iterable, Sequence

from app.components.degradation_detection.models import (
    AntiPatternInstance,
    ReleaseDetection,
    Timeline,
    TimelineEntry,
)
from app.domain.canonical_release import (
    CanonicalRelease,
    DependencyEdge,
    ElementSnapshot,
    GateStatus,
)
from app.domain.degradation_event import Scope
from app.domain.release_package import ArchitectureStyle

HASH = "sha256:" + "0" * 64


def el(
    element_id: str,
    *,
    name: str | None = None,
    kind: str = "service",
    size: float | None = 1000.0,
    size_unit: str | None = "loc",
    aliases: Iterable[str] = (),
) -> ElementSnapshot:
    """An element; its name defaults to its id."""
    return ElementSnapshot(
        element_id=element_id,
        name=element_id if name is None else name,
        kind=kind,
        size=size,
        size_unit=size_unit,
        aliases=tuple(aliases),
    )


def rel(
    release_id: str,
    elements: Iterable[ElementSnapshot | str],
    edges: Iterable[tuple[str, str]] = (),
) -> CanonicalRelease:
    """A release; a bare string is an element with that id and default attributes."""
    return CanonicalRelease(
        system_id="tiny",
        release_id=release_id,
        released_at=dt.datetime(2025, 1, 1, tzinfo=dt.UTC),
        architecture_style=ArchitectureStyle.MICROSERVICES,
        granularity="service",
        validation_confidence=0.9,
        gate_status=GateStatus.ACCEPTED,
        package_hash=HASH,
        elements=tuple(el(e) if isinstance(e, str) else e for e in elements),
        dependencies=tuple(
            DependencyEdge(from_id=a, to_id=b, types=("call",), count=1) for a, b in edges
        ),
    )


def timeline(*releases: CanonicalRelease) -> Timeline:
    """The releases in the order given, as M1 would have ordered them."""
    return Timeline(
        system_id="tiny",
        entries=tuple(TimelineEntry(ordinal=i, release=r) for i, r in enumerate(releases)),
    )


def no_detections(tl: Timeline) -> tuple[ReleaseDetection, ...]:
    """M2 ran nothing on any release: tracking then only builds lineages."""
    return tuple(
        ReleaseDetection(release_id=entry.release.release_id, observations=())
        for entry in tl.entries
    )


def instance(
    anti_pattern_type: str,
    *members: str,
    scope: Scope = Scope.INSTANCE,
    key: str | None = None,
) -> AntiPatternInstance:
    """An instance keyed like M2 keys it (smallest member, unless ``key`` is given).

    Its ``release_id`` is a placeholder; ``detections`` sets it to the release it is put in.
    """
    ordered = tuple(sorted(members))
    return AntiPatternInstance(
        release_id="-",
        local_instance_id=f"{anti_pattern_type}:{key or ordered[0]}",
        anti_pattern_type=anti_pattern_type,
        catalog="universal",
        scope=scope,
        members=ordered,
        measures={"member_count": float(len(ordered))},
    )


def detections(
    tl: Timeline,
    *per_release: Iterable[AntiPatternInstance],
    run: Sequence[str],
    not_run: dict[int, Sequence[str]] | None = None,
) -> tuple[ReleaseDetection, ...]:
    """One ``ReleaseDetection`` per timeline entry, from one list of instances per release.

    ``run`` are the detector ids that ran on every release, except those that ``not_run`` lists
    for a release index.
    """
    if len(per_release) != len(tl.entries):
        raise ValueError("give one list of instances per release")
    skipped = not_run or {}
    return tuple(
        ReleaseDetection(
            release_id=entry.release.release_id,
            observations=(),
            instances=tuple(
                i.model_copy(update={"release_id": entry.release.release_id}) for i in found
            ),
            detectors_run=tuple(d for d in run if d not in skipped.get(k, ())),
        )
        for k, (entry, found) in enumerate(zip(tl.entries, per_release, strict=True))
    )
