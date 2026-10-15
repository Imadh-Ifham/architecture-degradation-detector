"""Keeping a package small enough to ask, and saying what was left out.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    A package has to fit in a question. When it does not, something is
    dropped - and which something is decided here, in advance, by role.

    The order is the one `EvidenceRole` already declares: the rule is kept
    longest and structural context goes first. That is not an arbitrary
    ranking. A verdict can rest on the rule alone; it can never rest on a
    neighbour, which is context a reviewer uses rather than evidence a
    conclusion stands on.

    Two properties matter more than the policy itself.

    It is **deterministic**: the same package truncates the same way every
    time. The package's hash is the verdict cache's key, so truncation that
    varied between runs would miss the cache without saying so - and the rate
    limit would bite on the day it mattered.

    It is **reported**: `truncated` and `dropped_roles` travel on the package.
    A quietly shortened package produces a verdict that cannot be explained,
    and a weaker question deserves to be visible as one.

    The cap counts items rather than tokens. An item is a rule, a rationale or
    one neighbour, so items are a good enough proxy for size - and a
    per-model tokeniser would be a dependency, a download and a version to
    pin, for a number that only has to be an upper bound.
"""

from ..models import EvidenceItem, EvidenceRole

MAX_ITEMS = 12

_PRIORITY = {role: position for position, role in enumerate(EvidenceRole)}
"""How long each role is kept, read from the enum's own declaration order.

Read rather than restated, so the ranking cannot drift from the vocabulary it
ranks.
"""


def fit(
    items: tuple[EvidenceItem, ...], limit: int = MAX_ITEMS
) -> tuple[tuple[EvidenceItem, ...], tuple[EvidenceRole, ...]]:
    """Return the items that fit, and the roles that were dropped entirely.

    Items are removed from the weakest role first, and within a role in
    reverse order, so what survives is always a prefix of what was offered.
    """

    if len(items) <= limit:
        return items, ()

    kept = list(items)
    while len(kept) > limit:
        weakest = max(kept, key=lambda item: (_PRIORITY[item.role], kept.index(item)))
        kept.remove(weakest)

    surviving = {item.role for item in kept}
    dropped = tuple(
        role
        for role in EvidenceRole
        if role not in surviving and any(item.role is role for item in items)
    )
    return tuple(kept), dropped


__all__ = ["MAX_ITEMS", "fit"]
