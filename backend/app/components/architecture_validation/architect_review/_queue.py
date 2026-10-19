"""Turning classified facts into queue items.

Author: Aman Mohamed M.A
Date: 2026-10-19
Description:
    A pure function, kept apart from the service, for the reason M8 keeps its
    document builder apart: the part that can silently drop a field has
    nothing to do with a database, and this way it can be asserted with no
    queue, no run and no clock beyond the one passed in.

    Items hold references and never copies. The evidence and the candidate
    decision live in the knowledge log and the published document, and a
    second copy here would be the one that goes stale, with no way to tell
    which was right.
"""

import hashlib
from datetime import datetime

from ..models import ClassifiedFact, ReviewItem, Route


def items_for(
    facts: tuple[ClassifiedFact, ...],
    repository_id: str,
    release_id: str,
    created_at: datetime,
) -> tuple[ReviewItem, ...]:
    """One item per fact that a person has to look at.

    A fact routed to publish is never queued: the queue is the list of things
    the system would not claim on its own, and padding it with settled facts
    would make it a list of everything.
    """

    return tuple(
        _item(fact, repository_id, release_id, created_at)
        for fact in facts
        if fact.route == Route.REVIEW
    )


def _item(
    fact: ClassifiedFact,
    repository_id: str,
    release_id: str,
    created_at: datetime,
) -> ReviewItem:
    """One queued fact, with the references a person needs to judge it.

    `source_tier` is here for the architect rather than for the system. It is
    what lets the screen say *why* this needs a person - the only record of
    this rule is a design document - instead of showing a number below a
    threshold and leaving them to guess.
    """

    return ReviewItem(
        item_id=item_id(repository_id, release_id, fact.fact_id),
        fact_id=fact.fact_id,
        bucket=fact.bucket,
        confidence=fact.confidence,
        source_tier=fact.source_tier,
        evidence_refs=fact.evidence_refs,
        candidate_decision_id=fact.governing_decision,
        created_at=created_at,
    )


def item_id(repository_id: str, release_id: str, fact_id: str) -> str:
    """The item's identity, derived rather than generated.

    Content-addressed on the three things that make a queued fact the same
    queued fact, so a re-run of a release produces the identical id and the
    insert is a no-op. A generated id would make the second run's row a new
    row, and the unique index would then be rejecting rows the component
    thought were different.

    Short, because it is read off a screen and typed into a URL.
    """

    digest = hashlib.sha256(
        "|".join((repository_id, release_id, fact_id)).encode("utf-8")
    )
    return digest.hexdigest()[:16]
