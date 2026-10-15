"""Fact identity.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Gives every observed fact a stable id derived from its content.

    Content addressing rather than a counter or a UUID, for two reasons. The
    same relationship observed in two runs of the same release gets the same
    id, so results can be compared without matching on position. And the id of
    a fact in one release differs from the same relationship in the next, which
    is what the release component in the hash is for - a fact is about a
    release, not about a repository.

    Element names are canonicalised before hashing. Recovery reads names from
    manifests, and the same service can appear as "payment-service",
    "paymentservice" and "PaymentService" in different files of one repository.
    Without canonicalisation those are three elements, and a rule about one of
    them governs none of the others.

    The reduction itself lives one level up, in the component's `_identity`,
    because the knowledge model has to reduce the names a decision record
    writes in exactly the same way. Two implementations of it would mean a
    rule about "payment-service" quietly governing nothing.

    The same reduction can also merge two elements that are genuinely
    different, which is the one weakness of the approach. `collisions()` is
    the guard: it reports every case where that would happen, with both
    original names, and the run proceeds with them merged. A report is not a
    resolution - but an unreported merge cannot be resolved later at all.
"""

import hashlib
from collections.abc import Iterable

from .._identity import canonical_name

FACT_ID_LENGTH = 16


def collisions(names: Iterable[str]) -> dict[str, tuple[str, ...]]:
    """Group names that canonicalise alike, keeping only the groups above one.

    The guard on the one function this subcomponent's measured result rests
    on. `canonical_name` is what makes retrieval by identity possible, and the
    obvious attack on it is that it could merge two services that are
    genuinely different - `cart` and `cart-service` in one repository, meaning
    two things. This cannot tell those apart, and does not try: it reports
    where it would merge, with both originals, so the question becomes a count
    across the corpus rather than a denial.

    Returned as a mapping rather than warned about here, because this module
    knows about names and nothing else. The service decides what a collision
    means for a run.
    """

    grouped: dict[str, set[str]] = {}
    for name in names:
        grouped.setdefault(canonical_name(name), set()).add(name)

    return {
        key: tuple(sorted(originals))
        for key, originals in sorted(grouped.items())
        if len(originals) > 1
    }


def fact_id(subject: str, relationship: str, object_: str, release_id: str) -> str:
    """Return the content-addressed id for one observed fact.

    Built from a joined string with an explicit separator rather than from a
    dict, so the result cannot depend on key ordering, and so adding a field
    later is a deliberate change to the id rather than an accidental one.
    """

    material = "|".join(
        (
            canonical_name(subject),
            str(relationship).strip().lower(),
            canonical_name(object_),
            release_id.strip(),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:FACT_ID_LENGTH]


__all__ = ["FACT_ID_LENGTH", "canonical_name", "collisions", "fact_id"]
