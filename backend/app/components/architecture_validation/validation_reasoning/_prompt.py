"""The question, as the model receives it.

Author: Aman Mohamed M.A
Date: 2026-10-16
Description:
    Renders one sealed evidence package into the text of one request, and
    declares the shape the answer has to come back in.

    `render` takes the template and the package, and nothing else. That
    signature is the whole of Guard B's premise: the citations a model can
    make are checkable only because the set of things it was shown is finite
    and known, and a renderer that could reach the fact or the resolution
    directly would be showing it evidence nobody sealed - without breaking a
    single other test.

    Every item is printed with its reference, because a model cites what it
    can name, and with its role, because *this rule is in force* and *this one
    was replaced* are the same text otherwise.

    The evidence hash is deliberately not rendered. It is the cache key, not
    evidence, and a model given it would be given a number it cannot check.

    The schema is here rather than in a module of its own because it and the
    prompt are the two halves of one question: the prompt says what to answer
    and the schema says in what shape, and they are edited together or they
    disagree.

    `render_items` and `render_truncation_warning` are public because M5's
    renderer calls them. Both arms have to read the same evidence the same
    way, or a measured difference between them is partly a difference in
    formatting - which is the one thing a mechanism comparison cannot have.
"""

from ..models import EvidencePackage, PromptTemplate, Verdict

ITEM_SEPARATOR = "\n\n"

TRUNCATION_WARNING = (
    "Note: this evidence was shortened to fit a budget, and items of these "
    "kinds were dropped entirely: {roles}. Answer insufficient_evidence if "
    "what remains does not settle the question."
)


def render(template: PromptTemplate, package: EvidencePackage) -> str:
    """Build the request text for one package.

    The system rules and the question come back as one string because the
    provider sends one message. Keeping them as two sections in the file is
    what lets the rules be read and diffed on their own; promoting them to a
    `system` role would be a change to the adapter rather than to the prompt.
    """

    body = template.body
    for name, value in (
        ("release", package.release_id),
        ("subject", package.subject),
        ("relationship", str(package.relationship)),
        ("object", package.object),
        ("items", render_items(package)),
        ("warning", render_truncation_warning(package)),
    ):
        body = body.replace("{{" + name + "}}", value)

    return f"{template.system}\n\n{body}"


def verdict_schema() -> dict:
    """The shape a verdict has to come back in.

    `reasoning` and `cited_evidence_refs` are declared before `verdict`,
    which is what a reader of the schema expects of an answer meant to reason
    and then conclude. **Nothing may depend on it.** The order was believed to
    make the model commit to its reasoning before naming a conclusion; a spike
    on 2026-10-18 inspected the outgoing request and the responses and
    measured otherwise - the declared order survives `strictify` intact in
    both `properties` and `required`, and the provider returns the conclusion
    first regardless, identically on three consecutive calls at temperature
    zero. Strict decoding constrains which fields exist, their types and their
    permitted values, and leaves emission order to the model. The declaration
    stays because it costs nothing and because the day a provider honours it
    the property arrives for free.

    `verdict` is an enum rather than a string, so an answer outside the five
    values is impossible at generation time rather than something this code
    has to catch. The values come from `Verdict` itself, so the vocabulary
    offered to the model cannot drift from the one the pipeline accepts.

    `cited_evidence_refs` requires at least one entry. The schema can insist
    on that much; that the entries exist is Guard B's job and no schema's.
    """

    return {
        "type": "object",
        "properties": {
            "reasoning": {
                "type": "string",
                "description": (
                    "Why, in two or three sentences, referring to the "
                    "evidence by its references."
                ),
            },
            "cited_evidence_refs": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "The references actually used, and no others.",
            },
            "verdict": {
                "type": "string",
                "enum": [verdict.value for verdict in Verdict],
            },
        },
    }


def render_items(package: EvidencePackage) -> str:
    """Every item, in the order the package put them in.

    The order is the budget's truncation order, so what the model reads first
    is also what would survive a shortened package - and two packages for one
    fact at two budgets read as the same question, shortened.
    """

    return ITEM_SEPARATOR.join(
        f"[{item.ref}] {item.role}\n{item.text}" for item in package.items
    )


def render_truncation_warning(package: EvidencePackage) -> str:
    """What to say when the question was weakened to fit a budget.

    A package that quietly dropped a whole kind of evidence would be answered
    as confidently as a complete one. Only whole kinds are named: that items
    were dropped is `truncated`, and a model cannot act on "something went".
    """

    if not package.dropped_roles:
        return ""

    roles = ", ".join(str(role) for role in package.dropped_roles)
    return "\n" + TRUNCATION_WARNING.format(roles=roles) + "\n"


__all__ = [
    "render",
    "render_items",
    "render_truncation_warning",
    "verdict_schema",
]
