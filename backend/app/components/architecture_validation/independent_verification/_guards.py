"""The three checks a verifier's answer has to survive, none of them a model.

Author: Aman Mohamed M.A
Date: 2026-10-18
Description:
    A schema guarantees the outcome is one of three words, that every
    objection names one of four kinds, and that nothing else comes back. It
    cannot guarantee that an objection refers to anything real, and it cannot
    notice an answer that lists three faults and then concludes `agree`.

    So three guards run in plain Python after every answer:

      A  shape        the fields are there, both vocabularies hold, and an
                      objection about one item names an item
      B  reality      every reference an objection names exists in the package
      E  coherence    the outcome and the objections say the same thing

    **B is M4's function, imported, not reimplemented.** A verifier objecting
    to an item that does not exist is the verifier hallucinating, and it is
    rejected by the same ten lines that reject a reasoner's phantom citation.
    A second copy of one guarantee is how two implementations of it come to
    disagree.

    **M4's guards C and D do not apply here, and that is a decision rather
    than an omission.** Both are about what a *verdict* may rest on - a
    conclusion needs a rule and never a neighbour, and never the decision the
    resolver rejected. This answer is not a verdict. An objection pointing at
    a neighbour is a legitimate objection, and an objection pointing at the
    superseded item is precisely what this subcomponent exists to catch.

    E is the one that is new, and the failure it exists for is specific: ask a
    small model for a list of faults and a judgement in one response and it
    will sometimes write the faults and then agree anyway. The response is
    schema-valid, every reference resolves, and it contradicts itself.
"""

from ..models import (
    OBJECTIONS_ABOUT_ONE_ITEM,
    EvidencePackage,
    GuardFailure,
    Objection,
    ObjectionKind,
    VerificationOutcome,
)
from ..validation_reasoning._guards import check_citations_resolve
from ..validation_reasoning.models import GuardOutcome

ACCEPTED = GuardOutcome(accepted=True)

COHERENT_WITH_FAULTS = (VerificationOutcome.DISAGREE, VerificationOutcome.UNCERTAIN)
"""The outcomes that may carry objections.

`uncertain` may carry any number: a partial objection somebody could not
settle is a coherent thing to say. `disagree` must carry at least one, and
`agree` must carry none.
"""


def check(content: dict, package: EvidencePackage) -> GuardOutcome:
    """Run all three over one answer, and report the first that rejects it."""

    shape = check_shape(content)
    if not shape.accepted:
        return shape

    reality = check_citations_resolve(objection_refs(content), package)
    if not reality.accepted:
        return reality

    return check_coherence(content)


def check_shape(content: dict) -> GuardOutcome:
    """Guard A - the answer is the shape that was asked for.

    Mostly the schema's job already. This is the part that catches a provider
    which ignored it: strict mode is a request, and a request can be served by
    something that does not honour it.

    The last check is this subcomponent's own: an objection of a kind that is
    about one evidence item has to name the item. It is enforced here rather
    than left to `Objection` because a rejected answer must come back as a
    recorded guard failure and one identical retry, not as a `ValueError` out
    of a parser - and because inventing a reference to satisfy the type would
    be the one lie this subcomponent cannot afford.
    """

    if not isinstance(content, dict):
        return GuardOutcome(accepted=False, failure=GuardFailure.MALFORMED)

    reasoning = content.get("reasoning")
    objections = content.get("objections")

    if not isinstance(reasoning, str) or not reasoning.strip():
        return GuardOutcome(accepted=False, failure=GuardFailure.MALFORMED)
    if content.get("outcome") not in tuple(VerificationOutcome):
        return GuardOutcome(accepted=False, failure=GuardFailure.MALFORMED)
    if not isinstance(objections, list):
        return GuardOutcome(accepted=False, failure=GuardFailure.MALFORMED)

    for objection in objections:
        if not isinstance(objection, dict):
            return GuardOutcome(accepted=False, failure=GuardFailure.MALFORMED)

        kind = objection.get("kind")
        ref = objection.get("ref")
        statement = objection.get("statement")

        if kind not in tuple(ObjectionKind):
            return GuardOutcome(accepted=False, failure=GuardFailure.MALFORMED)
        if not isinstance(statement, str) or not statement.strip():
            return GuardOutcome(accepted=False, failure=GuardFailure.MALFORMED)
        if ref is not None and not isinstance(ref, str):
            return GuardOutcome(accepted=False, failure=GuardFailure.MALFORMED)
        if ObjectionKind(kind) in OBJECTIONS_ABOUT_ONE_ITEM and not ref:
            return GuardOutcome(accepted=False, failure=GuardFailure.MALFORMED)

    return ACCEPTED


def check_coherence(content: dict) -> GuardOutcome:
    """Guard E - the outcome and the objections say the same thing.

      `agree`      objections must be empty. Agreeing while listing faults
                   is not agreement
      `disagree`   objections must not be empty. Disagreeing with nothing to
                   point at is an opinion rather than a finding
      `uncertain`  any number. Uncertainty with a partial objection in it is
                   a coherent thing to say

    An incoherent answer is discarded rather than salvaged. Three good
    objections with the wrong label on them look recoverable, and recovering
    them would mean this code deciding what the model meant - which is exactly
    the judgement it is not entitled to make.
    """

    outcome = VerificationOutcome(content["outcome"])
    objections = content["objections"]

    if outcome is VerificationOutcome.AGREE and objections:
        return GuardOutcome(
            accepted=False,
            failure=GuardFailure.INCOHERENT_OUTCOME,
            refs_at_fault=objection_refs(content),
        )
    if outcome is VerificationOutcome.DISAGREE and not objections:
        return GuardOutcome(
            accepted=False, failure=GuardFailure.INCOHERENT_OUTCOME
        )
    return ACCEPTED


def objection_refs(content: dict) -> tuple[str, ...]:
    """Every reference the objections name, with the absent ones left out.

    Two of the four kinds are about the argument rather than about an item, so
    a null reference is correct for them and must not be handed to Guard B as
    a citation that failed to resolve.
    """

    objections = content.get("objections") or []
    return tuple(
        objection["ref"]
        for objection in objections
        if isinstance(objection, dict) and objection.get("ref")
    )


def objections_from(content: dict) -> tuple[Objection, ...]:
    """The accepted answer's objections, as the shapes the component publishes.

    Only ever called on content the guards accepted, which is why it does no
    checking of its own. `Objection` still refuses a missing reference on the
    two kinds that need one, so the two halves agree and neither is load
    bearing alone.
    """

    return tuple(
        Objection(
            kind=ObjectionKind(objection["kind"]),
            ref=objection["ref"] or None,
            statement=objection["statement"],
        )
        for objection in content["objections"]
    )


__all__ = [
    "check",
    "check_coherence",
    "check_shape",
    "objection_refs",
    "objections_from",
]
