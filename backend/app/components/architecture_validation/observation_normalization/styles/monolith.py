"""Monolith style adapter.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Normalises a monolithic or modular architecture.

        Modules depend on modules, in process. There is no transport to record and
        no rank to compute, so this is the thinnest adapter - which is itself worth
        noting: a style costing one short file is the evidence that the registry
        design earns its place.
"""

from app.domain.recovered_architecture import ArchitectureStyle, RecoveredArchitecture

from ...models import ObservedFact, RelationshipKind
from .._identity import fact_id
from .base import base_attributes


class MonolithAdapter:
    """One fact per module-to-module dependency."""

    style = ArchitectureStyle.MONOLITH

    def normalise(self, architecture: RecoveredArchitecture) -> tuple[ObservedFact, ...]:
        facts = []
        for relationship in architecture.relationships:
            source = architecture.element_by_id(relationship.source_id)
            target = architecture.element_by_id(relationship.target_id)
            if source is None or target is None:
                continue
            facts.append(
                ObservedFact(
                    fact_id=fact_id(
                        source.name,
                        RelationshipKind.DEPENDS_ON,
                        target.name,
                        architecture.release_id,
                    ),
                    release_id=architecture.release_id,
                    subject=source.name,
                    relationship=RelationshipKind.DEPENDS_ON,
                    object=target.name,
                    style_resolved=self.style,
                    quality=relationship.quality,
                    attributes=base_attributes(
                        relationship.label,
                        {"interaction": "in-process", **relationship.attributes},
                    ),
                )
            )
        return tuple(facts)
