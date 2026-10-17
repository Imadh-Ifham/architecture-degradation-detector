"""Small timelines for the M3 tests: releases built from element specs and an edge list."""

import datetime as dt
from collections.abc import Iterable

from app.components.degradation_detection.models import Timeline, TimelineEntry
from app.domain.canonical_release import (
    CanonicalRelease,
    DependencyEdge,
    ElementSnapshot,
    GateStatus,
)
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
