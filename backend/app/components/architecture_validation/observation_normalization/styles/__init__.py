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

from .base import COMMUNICATION_LABELS, DEPENDENCY_LABELS, StyleAdapter
from .event_driven import PUBLISH_LABELS, SUBSCRIBE_LABELS, EventDrivenAdapter
from .generic import GenericAdapter
from .layered import LayeredAdapter
from .microservices import MicroservicesAdapter
from .monolith import MonolithAdapter

GENERIC_STYLE_NAME = "generic"

KNOWN_LABELS = (
    COMMUNICATION_LABELS | DEPENDENCY_LABELS | PUBLISH_LABELS | SUBSCRIBE_LABELS
)
"""Every relationship label some adapter in this package recognises.

Assembled at the registry rather than in `base.py`, because the question it
answers is about the style layer as a whole: *did anything here understand this
word?* The event-driven adapter knows `publishes` and `consumes` and nothing
else does, so a check written against `base.py` alone would report those as
unrecognised on every event-driven release.

Used for counting, never for branching. A label outside this set is still
absorbed into a dependency with the original kept - the set exists so the run
can say how many words it did not understand, which is the difference between
"normalised generically" and "normalised generically, and here is what we did
not know".
"""

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
    "KNOWN_LABELS",
    "StyleAdapter",
    "adapter_for",
    "registered_styles",
]
