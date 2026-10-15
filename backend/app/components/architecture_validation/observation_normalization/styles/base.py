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

    ---------------------------------------------------------------------
    WHY TWO RELATIONSHIP KINDS ARE ENOUGH
    ---------------------------------------------------------------------

    The obvious objection to a two-value vocabulary is that it must be losing
    something. The test of whether it is big enough is not how expressive it
    looks - it is whether every constraint the decision model can resolve
    describes one of the two. Each one does:

        M2 constraint     needs from a fact                asks
        ---------------   ------------------------------   ---------------------
        must_not_call     communicates-with                does this call exist
                                                           when it was forbidden?
        may_call          communicates-with                is this call within
                                                           what was permitted?
        must_call_via     communicates-with + `via`        did it go through the
                                                           thing it had to?
        declared_rpc      communicates-with +              is the transport the
                          `observed_as`                    one that was declared?
        (layering)        depends-on + `layer_rank`        did a lower layer reach
                                                           up into a higher one?
        (structural)      depends-on                       does this dependency
                                                           exist when forbidden?

    Everything a rule needs is either the relationship kind or a **named
    attribute key**. Nothing needs the architectural style, which is what lets
    one validation algorithm serve every style instead of branching per style.

    So the pressure a new requirement puts on this module is usually a new
    attribute key, not a third relationship kind. A third kind would mean
    every rule downstream learning when to look for it; an attribute key means
    one adapter setting one thing.

    **And the mapping into the two kinds is load-bearing.** A label filed under
    the wrong one is invisible: the fact is produced, the run completes, and
    every rule of the other kind reports it as uncovered. `COMMUNICATION_LABELS`
    below records what that cost once.
"""

from typing import Protocol, runtime_checkable

from app.domain.recovered_architecture import (
    ArchitectureElement,
    ArchitectureStyle,
    RecoveredArchitecture,
)

from ...models import FactEndpoint, ObservedFact, RelationshipKind
from .._identity import canonical_name, fact_id
from ..._release import release_sort_key

COMMUNICATION_LABELS = frozenset(
    {
        "http",
        "https",
        "grpc",
        "rest",
        "tcp",
        "graphql",
        "soap",
        "websocket",
        "amqp",
        "kafka",
        "declared",
    }
)
"""Labels that mean one element talks to another over a transport.

`declared` is here and it is the one that needs explaining. Recovery - and the
stand-in substituting for it - reports a dependency as `declared` when an
artifact names both ends but nothing names the protocol: a deployment manifest
gives another service's address on a port nobody recognised. That is still one
service configured to talk to another, so it is a communication whose transport
is unknown rather than a dependency of some other kind.

**Leaving it out was a real defect, and it is worth knowing why.** Ten of the
fifteen relationships in the subject system's recorded snapshot carry this
label, and the other five differ only in that their port happened to be
recognised. With `declared` unmapped, identical evidence produced two different
canonical kinds - and the decision vocabulary maps `must_not_call` and
`may_call`, which is every network-policy rule the demonstration rests on, onto
`communicates-with` alone. Two thirds of the architecture would have been the
wrong kind for the only rules there are.
"""

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


def endpoint(element: ArchitectureElement) -> FactEndpoint:
    """One element, as a fact's end.

    The only place canonicalisation is applied to a name on its way into a
    fact, which is what makes "identity is decided once" true rather than
    intended.
    """

    return FactEndpoint(
        id=element.id,
        name=element.name,
        canonical=canonical_name(element.name),
    )


def observed_fact(
    architecture: RecoveredArchitecture,
    *,
    subject: ArchitectureElement,
    relationship: RelationshipKind,
    object_: ArchitectureElement,
    style_resolved: str,
    quality: str,
    label: str,
    extra: dict | None = None,
) -> ObservedFact:
    """Build one canonical fact, the same way for every style.

    Every adapter builds its facts through here rather than constructing the
    dataclass itself. There were seven construction sites across the five
    adapters, which is seven places to edit when a fact gains a field - and
    the one that gets missed produces facts subtly unlike the others for a
    release or two before anyone notices.

    It also puts the fields that are nobody's style-specific business in one
    place. The identity hash, the release sort key and the style's provenance
    are properties of the fact, not of the architectural style it came from,
    so they are computed here by definition rather than correctly in five
    files by inspection.

    An adapter decides the four things only it can know: the two elements, the
    canonical relationship, and the attributes its style carries. It hands over
    the elements themselves rather than their names, so it cannot accidentally
    hand over one without the other.
    """

    ends = (endpoint(subject), endpoint(object_))

    return ObservedFact(
        fact_id=fact_id(
            ends[0].canonical, relationship, ends[1].canonical, architecture.release_id
        ),
        release_id=architecture.release_id,
        release_sort_key=release_sort_key(architecture.release_id),
        subject=ends[0],
        relationship=relationship,
        object=ends[1],
        style_resolved=style_resolved,
        style_source=architecture.style_source,
        quality=quality,
        attributes=base_attributes(label, extra),
    )
