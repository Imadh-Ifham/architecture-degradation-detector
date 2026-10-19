"""The judge with no model in it.

Author: Aman Mohamed M.A
Date: 2026-10-16
Description:
    Whether an observed dependency is consistent with the decision that
    governs it, decided mechanically.

    This answers the one question nothing inside the two model stages can.
    The reasoner is a language model and the verifier is a different language
    model trained on an overlapping corpus; if both are confidently wrong in
    the same direction, every check downstream of them agrees with a wrong
    answer and nothing in the output looks unusual. A third model would not
    help - it buys another vote from the same electorate. So the third judge
    is a table with no weights in it, and the two answers are compared
    afterwards rather than one of them being told the other.

    It is only possible because the constraint vocabulary is closed. The
    resolver has already matched one record to one observed dependency, so
    what is left - does this dependency match this constraint - has four cases
    and no judgement in it.

    Two premises it trusts rather than rechecks. The pair was matched upstream,
    by the only thing holding the decision index; and `must_call_via` names
    the required intermediary in its object, which is how the configuration
    scan writes it. Rechecking the first would mean a second implementation of
    the lookup, which is two chances to disagree about which rule applies.

    Where a premise stops holding it abstains and says which one, because a
    table that answered everything would be reporting a check nothing made.
"""

from .._identity import canonical_name
from ..models import (
    WILDCARD,
    ArbiterCheck,
    ConstraintKind,
    DecisionRecord,
    ObservedFact,
    SourceTier,
    Verdict,
)

DECIDABLE_TIERS = (SourceTier.DECISION_RECORD, SourceTier.EXECUTABLE_CONFIG)
"""The tiers that state a pair rather than imply one.

A decision record and a manifest both *say* which two elements they are about.
A tier 3 to 5 record had its pair read out of prose, a commit history or a
naming convention, so the table's premise - that subject and object mean what
they say - is exactly what is in doubt.
"""


def decide(fact: ObservedFact, record: DecisionRecord) -> ArbiterCheck:
    """The verdict the governing record mechanically implies, or an abstention.

    Returns `CONFIRMS`, `CONTRADICTS` or `None`, always with the row of the
    table that produced it. Nothing here reads a prompt, a model or a file.
    """

    if record.source_tier not in DECIDABLE_TIERS:
        return ArbiterCheck(
            None,
            f"{record.decision_id} is {record.source_tier} and its pair was "
            "inferred from prose, so the table's premise does not hold",
        )

    if record.constraint is ConstraintKind.MAY_CALL:
        return ArbiterCheck(
            Verdict.CONFIRMS,
            f"the dependency is named as permitted by {record.decision_id}",
        )

    if record.constraint is ConstraintKind.MUST_NOT_CALL:
        if record.subject == WILDCARD and record.object == WILDCARD:
            return ArbiterCheck(
                Verdict.CONTRADICTS,
                f"nothing names this pair and {record.decision_id} makes the "
                "default deny",
            )
        return ArbiterCheck(
            Verdict.CONTRADICTS,
            f"the dependency is named as forbidden by {record.decision_id}",
        )

    if record.constraint is ConstraintKind.MUST_CALL_VIA:
        return _through_or_around(fact, record)

    if record.constraint is ConstraintKind.DECLARED_RPC:
        return _operation(fact, record)

    # A fifth constraint kind would arrive here, and an abstention would
    # report it as a fact the table looked at and could not decide. It did not
    # look at it.
    raise ValueError(f"the arbiter has no row for {record.constraint}")


def _through_or_around(fact: ObservedFact, record: DecisionRecord) -> ArbiterCheck:
    """Whether the dependency went through the required intermediary.

    A rule whose subject is the wildcard requires a mechanism of every element
    rather than of a pair, and it abstains. `frontend -> cartservice` does not
    bypass the overlay that service accounts are declared in - the rule is
    about another axis entirely, and contradicting there would be a false
    accusation with a table's authority behind it.
    """

    if record.subject == WILDCARD:
        return ArbiterCheck(
            None,
            f"{record.decision_id} requires a mechanism of every element "
            "rather than of a pair, so it does not speak to this dependency",
        )

    if canonical_name(record.object) == fact.object.canonical:
        return ArbiterCheck(
            Verdict.CONFIRMS,
            f"it goes through {record.object}, the intermediary "
            f"{record.decision_id} requires",
        )

    return ArbiterCheck(
        Verdict.CONTRADICTS,
        f"it bypasses {record.object}, the intermediary "
        f"{record.decision_id} requires",
    )


def _operation(fact: ObservedFact, record: DecisionRecord) -> ArbiterCheck:
    """Whether the operation the fact names is the one the contract declares.

    A fact observed from deployment manifests names no operation, so on
    today's input this row abstains - and the resolver never reaches it at
    all, because M2's table maps this constraint to no relationship. It still
    compares rather than confirming outright: an unconditional confirm would
    be a check that passed without looking, and the first fact to carry an
    operation would get a verdict about the wrong one that read exactly like a
    verdict about the right one.
    """

    observed = str(fact.attributes.get("operation", "")).strip().lower()

    if observed and observed == record.object.strip().lower():
        return ArbiterCheck(
            Verdict.CONFIRMS,
            f"the operation {record.object} is declared in the service "
            f"contract by {record.decision_id}",
        )

    return ArbiterCheck(
        None,
        f"{record.decision_id} declares the operation {record.object} and "
        f"this fact names {observed or 'none'}, so there is nothing to compare",
    )


__all__ = ["DECIDABLE_TIERS", "decide"]
