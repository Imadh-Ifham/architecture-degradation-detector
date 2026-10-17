"""The four checks a model's answer has to survive, none of them a model.

Author: Aman Mohamed M.A
Date: 2026-10-16
Description:
    A schema guarantees the verdict is one of five values and that the
    citation list is not empty. It cannot guarantee that the citations refer
    to anything: `["ADR-999"]` is perfectly schema-valid, and a verdict built
    on it is well formed, fluent and groundless.

    So four guards run in plain Python after every answer:

      A  shape          the fields are present and the verdict is in vocabulary
      B  reality        every cited reference exists in the package it came from
      C  role           a conclusion rests on a rule, never on a neighbour
      D  supersession   and never on the decision the resolver rejected

    B is the whole grounding guarantee. C and D close holes that were
    previously comments in other modules: M3's budget says in prose that a
    verdict may rest on the rule alone and never on a neighbour, and the
    replaced decision is legitimately in the package as context, with nothing
    about its shape to say it is not in force.

    They are functions over the answer and the package rather than methods on
    the service, because verification reuses B against a verifier's objections
    and a second copy of one guarantee is how two implementations of it come
    to disagree.

    The order is A, B, D, C. D before C because citing only the replaced
    decision fails both - it is not a rule in force and it cannot carry a
    conclusion - and of the two true statements the specific one is the one
    worth publishing.
"""

from ..models import EvidencePackage, EvidenceRole, GuardFailure, Verdict
from .models import GuardOutcome

ACCEPTED = GuardOutcome(accepted=True)

CONCLUSION_ROLES = (EvidenceRole.RULE, EvidenceRole.PERMITTED_SET)
"""The roles a `confirms` or `contradicts` may rest on.

A rule states what was decided; a permitted set is what evidences an absence
under a default refusal. Everything else in a package is why a rule exists,
what it replaced, or what else the two elements touch - context that can
support a conclusion but cannot be the whole of it.
"""

CONCLUSIVE_VERDICTS = (Verdict.CONFIRMS, Verdict.CONTRADICTS)
"""The two verdicts that accuse or clear something, so the two C applies to.

`partially_confirms`, `unrelated` and `insufficient_evidence` are allowed to
rest on context, because none of them claims the decision settles the matter.
"""


def check(content: dict, package: EvidencePackage) -> GuardOutcome:
    """Run all four over one answer, and report the first that rejects it."""

    shape = check_shape(content)
    if not shape.accepted:
        return shape

    refs = tuple(content["cited_evidence_refs"])
    verdict = Verdict(content["verdict"])

    reality = check_citations_resolve(refs, package)
    if not reality.accepted:
        return reality

    supersession = check_superseded_not_governing(refs, package)
    if not supersession.accepted:
        return supersession

    return check_citation_role(refs, package, verdict)


def check_shape(content: dict) -> GuardOutcome:
    """Guard A - the answer is the shape that was asked for.

    Mostly the schema's job already. This is the part that catches a provider
    which ignored it: strict mode is a request, and a request can be served by
    something that does not honour it.
    """

    if not isinstance(content, dict):
        return GuardOutcome(accepted=False, failure=GuardFailure.MALFORMED)

    reasoning = content.get("reasoning")
    refs = content.get("cited_evidence_refs")
    verdict = content.get("verdict")

    if not isinstance(reasoning, str) or not reasoning.strip():
        return GuardOutcome(accepted=False, failure=GuardFailure.MALFORMED)
    if verdict not in tuple(Verdict):
        return GuardOutcome(accepted=False, failure=GuardFailure.MALFORMED)
    if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
        return GuardOutcome(accepted=False, failure=GuardFailure.MALFORMED)
    if not refs:
        # Separate from malformed: the answer is well formed and cites
        # nothing, which is a grounding failure rather than a shape one.
        return GuardOutcome(accepted=False, failure=GuardFailure.NO_CITATION)

    return ACCEPTED


def check_citations_resolve(
    refs: tuple[str, ...], package: EvidencePackage
) -> GuardOutcome:
    """Guard B - every cited reference is one that was supplied.

    The whole grounding guarantee, and the reason the evidence package is
    sealed at all: the citations can be checked only because the set of things
    the model was shown is finite and known.

    The unresolved references travel back on the outcome. A rejection that
    says only *a citation did not resolve* cannot distinguish a model
    inventing a plausible document id from one citing a real decision that
    was not in this package, and those are different problems.
    """

    unresolved = tuple(sorted(set(refs) - package.refs))
    if unresolved:
        return GuardOutcome(
            accepted=False,
            failure=GuardFailure.UNRESOLVED_CITATION,
            refs_at_fault=unresolved,
        )
    return ACCEPTED


def check_superseded_not_governing(
    refs: tuple[str, ...], package: EvidencePackage
) -> GuardOutcome:
    """Guard D - the replaced decision is context, never the rule in force.

    The package carries it deliberately: showing that the earlier decision was
    considered and correctly rejected is the demonstration's point. A verdict
    resting on it is the single most embarrassing output this component could
    produce, and it would look entirely normal.

    Rejected when the citations include a superseded item and nothing that can
    carry a conclusion. Citing it *beside* the rule is correct and is how a
    model shows it read the whole package.
    """

    roles = {item.ref: item.role for item in package.items}
    superseded = [ref for ref in refs if roles.get(ref) is EvidenceRole.SUPERSEDED]
    conclusive = [ref for ref in refs if roles.get(ref) in CONCLUSION_ROLES]

    if superseded and not conclusive:
        return GuardOutcome(
            accepted=False,
            failure=GuardFailure.SUPERSEDED_AS_GOVERNING,
            refs_at_fault=tuple(superseded),
        )
    return ACCEPTED


def check_citation_role(
    refs: tuple[str, ...], package: EvidencePackage, verdict: Verdict
) -> GuardOutcome:
    """Guard C - a conclusion rests on a rule, not on a neighbour.

    Only the two conclusive verdicts are held to it. `unrelated` and
    `insufficient_evidence` are honest answers *about* a package and may cite
    whatever led to them; `confirms` and `contradicts` are claims about what
    was decided, and a neighbourhood sentence decides nothing.
    """

    if verdict not in CONCLUSIVE_VERDICTS:
        return ACCEPTED

    roles = {item.ref: item.role for item in package.items}
    if any(roles.get(ref) in CONCLUSION_ROLES for ref in refs):
        return ACCEPTED

    return GuardOutcome(
        accepted=False,
        failure=GuardFailure.CONTEXT_ONLY_CITATION,
        refs_at_fault=tuple(refs),
    )


__all__ = [
    "CONCLUSION_ROLES",
    "check",
    "check_citation_role",
    "check_citations_resolve",
    "check_shape",
    "check_superseded_not_governing",
]
