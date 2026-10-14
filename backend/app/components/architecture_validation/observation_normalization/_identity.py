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
"""

import hashlib
import re

_SEPARATORS = re.compile(r"[\s_\-.]+")
_NOISE_SUFFIXES = ("-service", "service", "-svc", "svc", "-deployment", "-deploy")

FACT_ID_LENGTH = 16


def canonical_name(name: str) -> str:
    """Reduce a name to the form used for identity.

    Lowercased, separators removed, and one trailing "service" variant
    stripped. Only one suffix is removed, so "paymentservice" and
    "payment-service" unify while a service genuinely called "serviceservice"
    does not collapse to nothing.
    """

    reduced = _SEPARATORS.sub("", name.strip().lower())
    for suffix in _NOISE_SUFFIXES:
        candidate = suffix.replace("-", "")
        if reduced.endswith(candidate) and len(reduced) > len(candidate):
            return reduced[: -len(candidate)]
    return reduced


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
