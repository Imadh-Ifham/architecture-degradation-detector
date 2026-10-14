"""Layered style adapter.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Normalises a layered architecture.

        Layers depend on layers, and what makes the style interesting is that the
        dependency has a direction with a rank attached: presentation may depend on
        domain, and domain depending on presentation is the violation.

        The rank is carried as an attribute so a rule about layering direction can
        be evaluated downstream without the reasoner knowing what a layer is.
"""

from app.domain.recovered_architecture import (
    ArchitectureStyle,
    ElementKind,
    RecoveredArchitecture,
)

from ...models import ObservedFact, RelationshipKind
from .base import observed_fact

LAYER_RANKS = {
    "presentation": 1,
    "ui": 1,
    "api": 2,
    "application": 3,
    "service": 3,
    "domain": 4,
    "business": 4,
    "persistence": 5,
    "data": 5,
    "infrastructure": 6,
}
"""Conventional ranks, outermost first.

A name not in this table gets no rank rather than a guessed one. An invented
rank would make a layering verdict look computed when it was assumed.
"""


class LayeredAdapter:
    """One fact per inter-layer dependency, carrying the rank direction."""

    style = ArchitectureStyle.LAYERED

    def normalise(self, architecture: RecoveredArchitecture) -> tuple[ObservedFact, ...]:
        facts = []
        for relationship in architecture.relationships:
            source = architecture.element_by_id(relationship.source_id)
            target = architecture.element_by_id(relationship.target_id)
            if source is None or target is None:
                continue

            extra = {"interaction": "in-process"}
            source_rank = self._rank(source.name)
            target_rank = self._rank(target.name)
            if source_rank and target_rank:
                extra["layer_rank"] = f"{source_rank}->{target_rank}"
                extra["inward"] = source_rank < target_rank
            if source.kind is ElementKind.LAYER or target.kind is ElementKind.LAYER:
                extra["layer_relationship"] = True

            facts.append(
                observed_fact(
                    architecture,
                    subject=source,
                    relationship=RelationshipKind.DEPENDS_ON,
                    object_=target,
                    style_resolved=self.style,
                    quality=relationship.quality,
                    label=relationship.label,
                    extra={**extra, **relationship.attributes},
                )
            )
        return tuple(facts)

    def _rank(self, name: str) -> int | None:
        lowered = name.lower()
        for token, rank in LAYER_RANKS.items():
            if token in lowered:
                return rank
        return None
