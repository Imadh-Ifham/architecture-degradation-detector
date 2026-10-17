"""M1 steps 3-4: validated package -> ``CanonicalRelease``, and the package hash (pure).

Normalisation makes every package look the same to later modules, whatever C2 left out:

- ``name`` defaults to the element id and ``kind`` to the release ``granularity``;
- C1 metrics get a ``c1.`` prefix so they cannot collide with metrics C3 computes;
- duplicate edges collapse into one (counts summed, types merged), because the graph has one
  edge per ordered pair; self-loops are dropped and logged, because a dependency of an element
  on itself is not architectural coupling;
- elements and edges are sorted, so the result does not depend on the order C2 wrote them in.
"""

from collections import defaultdict

import structlog

from app.components.degradation_detection.ingestion.models import SELF_LOOP_DROPPED
from app.domain.canonical_release import (
    CanonicalRelease,
    DatastoreAccess,
    DependencyEdge,
    ElementSnapshot,
    GateStatus,
    IntentEntry,
)
from app.domain.release_package import Element, ReleasePackageV1
from app.shared.canonical_json import content_hash

log = structlog.get_logger(__name__)

C1_METRIC_PREFIX = "c1."


def package_hash(package: ReleasePackageV1) -> str:
    """``sha256:<hex>`` of the validated package, the identity used for idempotency.

    The hash is taken over the validated model, not the raw text: key order, whitespace,
    unknown fields (ignored by the tolerant reader) and the deprecated ``adr_ref`` spelling do
    not change what C3 reads, so they do not change the hash either.
    """
    return content_hash(package.model_dump(mode="json", by_alias=True))


def _element(element: Element, granularity: str) -> ElementSnapshot:
    return ElementSnapshot(
        element_id=element.id,
        name=element.name or element.id,
        kind=element.kind or granularity,
        size=element.size,
        size_unit=element.size_unit,
        aliases=tuple(element.aliases),
        layer=element.layer,
        metrics={f"{C1_METRIC_PREFIX}{name}": value for name, value in element.metrics.items()},
        extra=element.extra,
    )


def _edges(package: ReleasePackageV1) -> tuple[DependencyEdge, ...]:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    types: dict[tuple[str, str], set[str]] = defaultdict(set)
    for dependency in package.dependencies:
        if dependency.from_ == dependency.to:
            log.info(
                SELF_LOOP_DROPPED,
                reason=SELF_LOOP_DROPPED,
                system_id=package.system_id,
                release_id=package.release_id,
                element_id=dependency.from_,
            )
            continue
        pair = (dependency.from_, dependency.to)
        counts[pair] += dependency.count
        types[pair].update(dependency.types)
    return tuple(
        DependencyEdge(from_id=a, to_id=b, types=tuple(sorted(types[(a, b)])), count=counts[(a, b)])
        for a, b in sorted(counts)
    )


def normalise(
    package: ReleasePackageV1, *, gate_status: GateStatus, package_hash: str
) -> CanonicalRelease:
    datastore_access = (
        None
        if package.datastore_access is None
        else tuple(
            DatastoreAccess(element_id=access.element, datastore=access.datastore, mode=access.mode)
            for access in package.datastore_access
        )
    )
    return CanonicalRelease(
        system_id=package.system_id,
        release_id=package.release_id,
        released_at=package.released_at,
        architecture_style=package.architecture_style,
        granularity=package.granularity,
        validation_confidence=package.validation_confidence,
        gate_status=gate_status,
        package_hash=package_hash,
        elements=tuple(
            _element(element, package.granularity)
            for element in sorted(package.elements, key=lambda e: e.id)
        ),
        dependencies=_edges(package),
        intent=tuple(
            IntentEntry(
                intent_id=entry.intent_id,
                element_id=entry.element,
                source_type=entry.source_type,
                ref=entry.ref,
                decision=entry.decision,
                decision_kind=entry.decision_kind,
                date=entry.date,
            )
            for entry in package.intent
        ),
        datastore_access=datastore_access,
        delegation=None if package.delegation is None else tuple(package.delegation),
        c1_model_ref=package.provenance.c1_model_ref,
        c2_validation_ref=package.provenance.c2_validation_ref,
    )
