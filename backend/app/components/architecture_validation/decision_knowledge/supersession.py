"""Which decision was in force, at one release.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    The core of the component, and the shortest file in it.

    One rule: a decision governs a release when the release falls inside
    `[valid_from, valid_to)`. Half-open, so a decision and the decision that
    replaced it never both apply - with a closed upper bound the release
    exactly on the boundary belongs to two of them and the answer comes back
    ambiguous for no reason anybody could explain. The demonstration's own
    release is exactly such a boundary.

    Three answers and no fourth. One decision governs; two cover the release
    and neither is stronger, so the answer is that the recorded intent
    contradicts itself; or nothing speaks to this relationship at all. Nothing
    here invents a tiebreak - a resolution nobody can tell from a lucky guess
    is worth less than an honest refusal.

    What each constraint speaks about, which is the table the rest of the
    pipeline relies on and the one place it is written down:

      constraint        governs                   because
      ----------------  ------------------------  --------------------------
      may_call          communicates-with         one element reaching another
      must_not_call     communicates-with         the same, prohibited
      must_call_via     communicates-with         the same, through a third
      declared_rpc      nothing, yet              it is about an operation, and
                                                  an observed fact has none

    A `depends-on` fact is deliberately governed by none of them. The label
    means the dependency is real and the transport unknown, and a rule about
    who may *call* whom is not a rule about that - attaching one would put a
    communication verdict on an edge nobody claimed was a call.

    And the sentence the Tier-2 argument rests on, stated here because this is
    where it is acted upon: in Kubernetes, once any network policy selects a
    pod, traffic that no policy permits is denied. So the *absence* of a
    permission is itself a decision, and that is what makes configuration as
    strong as a written record for a structural rule. In the subject system it
    is not even an inference - a policy selecting every pod and permitting
    nothing is committed in the repository.

    Two pieces of ordering that are not the interval:

    `a stronger source wins`. The same relationship can be described by a
    decision somebody wrote and by a rule reconstructed from configuration. A
    written record is tier 1 and takes precedence, and the source that
    disagreed is reported rather than dropped - a declared decision and a
    running configuration saying different things is a finding about the
    system, not noise.

    `a specific permission beats the general refusal`. A default-deny policy
    is one record about every pair, so it is looked at only when no rule names
    this pair directly. The alternative - expanding it into one refusal per
    unpermitted pair - would be 116 records on a twelve-element system, all
    saying the same thing, and would bury the rules that mean something.
"""

from collections.abc import Sequence

from .._release import release_sort_key
from ..models import (
    ConstraintKind,
    DecisionRecord,
    ObservedFact,
    RelationshipKind,
    Resolution,
    SourceTier,
)
from .models import DecisionVersion

WILDCARD = "*"

CONSTRAINT_RELATIONSHIP: dict[ConstraintKind, RelationshipKind | None] = {
    ConstraintKind.MAY_CALL: RelationshipKind.COMMUNICATES_WITH,
    ConstraintKind.MUST_NOT_CALL: RelationshipKind.COMMUNICATES_WITH,
    ConstraintKind.MUST_CALL_VIA: RelationshipKind.COMMUNICATES_WITH,
    ConstraintKind.DECLARED_RPC: None,
}
"""Which kind of observed relationship each constraint speaks about.

The three communication constraints all describe one element reaching another,
which is what `communicates-with` is. `declared_rpc` describes an operation a
service exposes, and an observed fact carries no operation - so it is held in
the log, reported in the counts, and governs nothing until a fact exists that
names an operation.

A `depends-on` fact is deliberately not governed by a communication rule. The
label means the dependency is real and the transport unknown, and a rule about
who may *call* whom is not a rule about that.
"""

_TIER_ORDER = tuple(SourceTier)
"""Tiers, strongest first, taken from the enum's own declaration order.

Read from the enum rather than restated, so the ranking cannot drift from the
vocabulary it ranks.
"""


def constraints_for(relationship: RelationshipKind) -> tuple[ConstraintKind, ...]:
    """Every constraint kind that can govern this kind of relationship."""

    return tuple(
        constraint
        for constraint, governs in CONSTRAINT_RELATIONSHIP.items()
        if governs == relationship
    )


def covers(version: DecisionVersion, release_id: str) -> bool:
    """Whether this version was in force at `release_id`.

    `[valid_from, valid_to)` - the start included, the end excluded.
    """

    release = release_sort_key(release_id)
    if release < release_sort_key(version.valid_from):
        return False
    if version.valid_to is None:
        return True
    return release < release_sort_key(version.valid_to)


def strength_of(version: DecisionVersion) -> int:
    """How strong a version's source is; lower is stronger."""

    return _TIER_ORDER.index(version.record.source_tier)


def resolve_fact(index, fact: ObservedFact) -> Resolution:
    """Which decision governs this fact, at this fact's release."""

    constraints = constraints_for(fact.relationship)
    if not constraints:
        return Resolution(governing=None, uncovered=True)

    direct = _covering(
        index, fact.subject.canonical, constraints, fact.object.canonical, fact.release_id
    )
    if direct:
        return _decide(index, direct)

    general = _covering(index, WILDCARD, constraints, WILDCARD, fact.release_id)
    if general:
        return _decide(index, general)

    return Resolution(governing=None, uncovered=True)


def _covering(
    index,
    subject: str,
    constraints: Sequence[ConstraintKind],
    object_: str,
    release_id: str,
) -> list[DecisionVersion]:
    return [
        version
        for constraint in constraints
        for version in index.versions_of(subject, constraint, object_)
        if covers(version, release_id)
    ]


def _decide(index, candidates: list[DecisionVersion]) -> Resolution:
    """Pick the governing version, or report that nothing can be picked."""

    strongest = min(strength_of(version) for version in candidates)
    contenders = [v for v in candidates if strength_of(v) == strongest]

    if len(contenders) > 1:
        return Resolution(
            governing=None,
            ambiguous=True,
            candidates=tuple(sorted(v.record.decision_id for v in contenders)),
        )

    governing = contenders[0]
    disagreeing = {
        version.record.source
        for version in candidates
        if version.record.constraint is not governing.record.constraint
    }

    return Resolution(
        governing=governing.record,
        superseded_ancestor=_ancestor(index, governing),
        conflicting_sources=tuple(sorted(disagreeing)),
    )


def _ancestor(index, version: DecisionVersion) -> str | None:
    """The decision this one replaced, so the chain can be shown.

    Named by the replacement itself where the scan worked it out, and found by
    looking for the version that ended exactly where this one began otherwise.
    Resolving to the right decision while forgetting the one it replaced is a
    right answer that cannot be defended.
    """

    record: DecisionRecord = version.record
    if record.supersedes:
        return record.supersedes

    for other in index.versions_of(record.subject, record.constraint, record.object):
        if other.valid_to == version.valid_from:
            return other.record.decision_id
    return None


__all__ = [
    "CONSTRAINT_RELATIONSHIP",
    "WILDCARD",
    "constraints_for",
    "covers",
    "resolve_fact",
    "strength_of",
]
