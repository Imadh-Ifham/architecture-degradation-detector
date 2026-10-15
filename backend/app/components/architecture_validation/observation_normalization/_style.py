"""Architectural style inference, and the authority rule around it.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    Works out the architectural style when recovery did not supply one, and
    never when it did.

    The architecture document gives recovery the job of detecting the style -
    the snapshot is to hold "the elements, their dependencies and the detected
    architectural style". So when a style arrives, it stands, and this module
    is not consulted. When none arrives, this module answers and the answer is
    labelled `inferred_by_c2` on the run and on every fact, because an
    assumption nobody can check is worse than a weaker answer that says so.

    Why the inference lives here rather than in the gateway, where it started.
    There are three readers behind M1's one port - a recorded snapshot,
    recovery's inventory document, and eventually recovery's graph - and an
    inference in the gateway would be written once per reader or imported
    across them. It depends on nothing but the elements and the relationships,
    which is to say on nothing a reader has and the normaliser does not, so one
    copy here serves all three and the rule about whose answer wins is stated
    in one place.

    The rules are deliberately narrow, and the narrowness is the point. Each
    one is a thing the input states outright; none of them is a heuristic
    dressed up as a classification.
"""

from app.domain.recovered_architecture import (
    ArchitectureElement,
    ArchitectureRelationship,
    ArchitectureStyle,
    ElementKind,
)

MICROSERVICE_MINIMUM_SERVICES = 2
"""How many deployed services make an architecture microservices.

Two. One deployed service is a deployed monolith, and calling that
microservices because it has a manifest would be the kind of guess this module
exists to avoid.
"""

LAYER_TOKENS = ("presentation", "domain", "application", "persistence", "infrastructure")
"""Layer names recognised outright. Two of them have to appear before the
architecture is called layered: one component called `domain` is a component
called domain, not evidence of a layered architecture."""

LAYER_TOKEN_MINIMUM = 2


def infer_style(
    elements: tuple[ArchitectureElement, ...],
    relationships: tuple[ArchitectureRelationship, ...] = (),
) -> ArchitectureStyle:
    """Infer the style from the architecture alone, or report that it could not be.

    Returns `UNKNOWN` rather than a best guess. That routes the release to the
    generic adapter, which keeps every relationship and caps how strong any
    verdict about it may become - a correct answer about an architecture whose
    style is undetermined, rather than a confident answer about the wrong one.

    `relationships` is accepted and deliberately unused. Every style that can
    be told apart from the others needs only the elements, and the one that
    would need the relationships - event-driven - is not inferred at all:
    recognising it takes evidence of a broker and of publish and subscribe
    pairs, which nothing upstream supplies yet. The parameter is here so that
    adding that rule later is a change inside this function rather than a
    change to its callers.
    """

    services = [element for element in elements if element.kind is ElementKind.SERVICE]
    if len(services) >= MICROSERVICE_MINIMUM_SERVICES:
        return ArchitectureStyle.MICROSERVICES

    names = " ".join(element.name.lower() for element in elements)
    if sum(token in names for token in LAYER_TOKENS) >= LAYER_TOKEN_MINIMUM:
        return ArchitectureStyle.LAYERED

    if len(elements) == 1:
        return ArchitectureStyle.MONOLITH

    return ArchitectureStyle.UNKNOWN


__all__ = [
    "LAYER_TOKENS",
    "LAYER_TOKEN_MINIMUM",
    "MICROSERVICE_MINIMUM_SERVICES",
    "infer_style",
]
