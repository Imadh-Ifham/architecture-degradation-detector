"""The challenge, as the verifier receives it.

Author: Aman Mohamed M.A
Date: 2026-10-18
Description:
    Renders one sealed evidence package and one verdict into the text of one
    request, and declares the shape the objections have to come back in.

    `render` takes the template, the package and the verdict, and nothing
    else. The extra argument against M4's renderer is the whole of this
    subcomponent: the verifier is shown the claim deliberately, because a
    verifier that cannot see it is running the reasoner's task a second time
    and measuring the model's self-consistency rather than checking anything.

    The citations are rendered as well as the reasoning. An objection of the
    kind *this cited item does not say that* is not answerable without
    knowing which items were cited, and a verifier left to guess would object
    to the argument it imagined.

    This is a separate file from M4's and a separate prompt from M4's, never
    the primary prompt behind a flag. Two arms that share a template are
    indistinguishable in the results, and the mechanism comparison this
    component is built to support needs them apart.
"""

from ..models import (
    EvidencePackage,
    ObjectionKind,
    PrimaryVerdict,
    PromptTemplate,
    VerificationOutcome,
)
from ..validation_reasoning._prompt import render_items, render_truncation_warning

REF_SEPARATOR = ", "


def render(
    template: PromptTemplate, package: EvidencePackage, verdict: PrimaryVerdict
) -> str:
    """Build the request text for one challenge.

    The items and the truncation warning are rendered by M4's functions
    rather than by copies of them. Both arms have to read the same evidence
    the same way or a difference between them is partly a difference in
    formatting, which is the one thing a mechanism comparison cannot have.
    """

    body = template.body
    for name, value in (
        ("release", package.release_id),
        ("subject", package.subject),
        ("relationship", str(package.relationship)),
        ("object", package.object),
        ("items", render_items(package)),
        ("warning", render_truncation_warning(package)),
        ("verdict", str(verdict.verdict)),
        ("reasoning", verdict.reasoning),
        ("cited", REF_SEPARATOR.join(verdict.cited_evidence_refs)),
    ):
        body = body.replace("{{" + name + "}}", value)

    return f"{template.system}\n\n{body}"


def verification_schema() -> dict:
    """The shape a set of objections has to come back in.

    `reasoning` and then `objections` are declared before `outcome`, which is
    what a reader of the schema expects of a response meant to find faults and
    then conclude from them. **Nothing may depend on it.** The order survives
    `strictify` intact and the provider returns its conclusion first anyway,
    measured on repeated calls at temperature zero, so the declaration is a
    request and not a property. Coherence between the fields is enforced by a
    guard after the answer arrives.

    `reasoning` is asked for rather than derived here, because `uncertain` is
    an outcome that carries no objections and would otherwise arrive with
    nothing explaining it - a verifier saying *I cannot tell* and giving no
    reason is an answer a reviewer can do nothing with. The model's own words
    about each individual fault still live in `objections[].statement`; this
    field is what it says about the argument as a whole.

    `kind` and `outcome` are closed enums rather than strings, so a value
    outside either vocabulary is impossible at generation time instead of
    being something the guards have to catch. Both lists are built from the
    enums themselves, so what is offered to the model cannot drift from what
    the pipeline accepts.

    `ref` is a union with null rather than an absent property. Strict mode
    has no notion of an optional field - `strictify` makes every property
    required - so the two kinds of objection that have no item to name have
    to be able to send `null` for it.

    `objections` has no `minItems`. An empty list is the correct answer when
    the argument holds, and a schema that demanded one fault would guarantee
    that one was always found.
    """

    return {
        "type": "object",
        "properties": {
            "reasoning": {
                "type": "string",
                "description": (
                    "What is or is not wrong with the argument, in one or two "
                    "sentences, referring to the evidence by its references."
                ),
            },
            "objections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": [kind.value for kind in ObjectionKind],
                        },
                        "ref": {
                            "type": ["string", "null"],
                            "description": (
                                "The reference this objection is about, for "
                                "citation_does_not_support and "
                                "overlooked_evidence. Null for the other two."
                            ),
                        },
                        "statement": {
                            "type": "string",
                            "description": "The fault, in one sentence.",
                        },
                    },
                },
                "description": "Empty if the argument holds.",
            },
            "outcome": {
                "type": "string",
                "enum": [outcome.value for outcome in VerificationOutcome],
            },
        },
    }


__all__ = ["render", "verification_schema"]
