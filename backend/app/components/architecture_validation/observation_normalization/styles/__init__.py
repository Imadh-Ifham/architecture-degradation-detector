"""Style adapter registry.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Maps an architectural style to the adapter that normalises it.

    Adding a style is adding one module and one line here. There is
    deliberately no branch on style anywhere else in the component: a chain of
    style conditionals is what the research design rejected, because the
    branches drift apart and no single one is ever fully tested.

    An unregistered style resolves to the generic adapter rather than raising.
    A style nobody has written an adapter for is still worth validating, with
    the structure preserved and the confidence capped - and saying "style not
    resolved" is better than guessing a style and letting every downstream
    decision silently inherit the guess.
"""

from app.domain.recovered_architecture import ArchitectureStyle

from .base import StyleAdapter
from .event_driven import EventDrivenAdapter
from .generic import GenericAdapter
from .layered import LayeredAdapter
from .microservices import MicroservicesAdapter
from .monolith import MonolithAdapter

GENERIC_STYLE_NAME = "generic"

_ADAPTERS: dict[ArchitectureStyle, StyleAdapter] = {
    adapter.style: adapter
    for adapter in (
        MicroservicesAdapter(),
        LayeredAdapter(),
        EventDrivenAdapter(),
        MonolithAdapter(),
    )
}

_GENERIC = GenericAdapter()


def adapter_for(style: ArchitectureStyle) -> StyleAdapter:
    """Return the adapter for `style`, or the generic adapter."""

    return _ADAPTERS.get(style, _GENERIC)


def registered_styles() -> tuple[ArchitectureStyle, ...]:
    """Every style with a dedicated adapter, excluding the fallback.

    Exposed so the cost of supporting a new style can be stated as a fact
    rather than estimated.
    """

    return tuple(sorted(_ADAPTERS))


__all__ = [
    "GENERIC_STYLE_NAME",
    "StyleAdapter",
    "adapter_for",
    "registered_styles",
]
