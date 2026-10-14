"""Style adapter protocol and canonical reduction.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    What every style adapter has to provide, and the shared pieces each one
    uses to get there.

    An adapter's whole job is to reduce one architectural style's way of
    describing a relationship into the canonical triple, keeping everything
    style-specific in the fact's attributes. Nothing downstream learns which
    adapter ran, which is what lets one validation algorithm serve every
    style instead of branching per style.

    Written before any adapter existed, on purpose. A protocol shaped around
    the first adapter that happens to be written tends not to fit the second,
    and then it is paid for twice.
"""

from typing import Protocol, runtime_checkable

from app.domain.recovered_architecture import (
    ArchitectureStyle,
    RecoveredArchitecture,
)

from ...models import ObservedFact, RelationshipKind

COMMUNICATION_LABELS = frozenset(
    {"http", "https", "grpc", "rest", "tcp", "graphql", "soap", "websocket", "amqp", "kafka"}
)
"""Labels that mean one element talks to another over a transport."""

DEPENDENCY_LABELS = frozenset(
    {"depends", "depends-on", "depends_on", "uses", "imports", "includes", "references"}
)
"""Labels that mean one element needs another, without naming a transport."""


@runtime_checkable
class StyleAdapter(Protocol):
    """Reduces one architectural style into canonical observed facts.

    `style` is what the registry keys on. `normalise` receives the whole
    architecture rather than one relationship at a time, because some styles
    need to look across relationships: an event-driven publish and subscribe
    pair only becomes one fact when both halves are visible together.
    """

    style: ArchitectureStyle

    def normalise(self, architecture: RecoveredArchitecture) -> tuple[ObservedFact, ...]:
        """Return one canonical fact per logical relationship."""
        ...


def classify_label(label: str) -> RelationshipKind:
    """Reduce a style's relationship label to the canonical vocabulary.

    Falls back to a dependency rather than raising. An unrecognised label
    still describes a real relationship between two elements, and the original
    label is kept in the fact's attributes - so nothing is lost, and the
    unknown case is visible rather than dropped.
    """

    normalised = label.strip().lower()
    if normalised in COMMUNICATION_LABELS:
        return RelationshipKind.COMMUNICATES_WITH
    return RelationshipKind.DEPENDS_ON


def base_attributes(label: str, extra: dict | None = None) -> dict:
    """The attributes every fact carries, plus the style's own.

    `observed_as` keeps the original label. It is what makes a reduction
    auditable: a reader can see that "grpc" became "communicates-with" rather
    than having to trust that it did.
    """

    attributes = {"observed_as": label}
    if extra:
        attributes.update(extra)
    return attributes
