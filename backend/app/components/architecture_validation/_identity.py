"""Element identity.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    One reduction from a written element name to the identity this component
    matches on.

    It sits at the component level rather than inside a subcomponent because
    two of them now need the same answer. Normalisation canonicalises the
    names recovery reports; the knowledge index canonicalises the names a
    policy document or a decision record writes. If those two reductions ever
    differed, a rule about `payment-service` would govern nothing in an
    architecture whose element is called `paymentservice` - and nothing would
    say so, because the lookup would simply find no decision and the fact
    would be reported as uncovered.

    The same reduction can also merge two elements that are genuinely
    different, which is its one weakness. Normalisation reports where that
    happens, with both original names, so the question is a count rather than
    a denial.
"""

import re

_SEPARATORS = re.compile(r"[\s_\-.]+")
_NOISE_SUFFIXES = ("-service", "service", "-svc", "svc", "-deployment", "-deploy")


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


__all__ = ["canonical_name"]
