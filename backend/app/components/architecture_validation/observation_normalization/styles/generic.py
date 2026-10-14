"""Generic style adapter.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Normalises an architecture whose style could not be determined.

        Not a consolation prize. The structure is preserved in full and every
        relationship still becomes a fact, so an unknown style validates rather
        than failing.

        What it does not do is guess. The canonical relationship falls back to a
        dependency, the original label is kept, and `style_resolved` says
        "generic" - which the classification rules read as a reason to cap how
        strong any verdict about these facts may become.

        The alternative, picking the most likely style, would be worse in a way
        that is hard to detect later: every downstream decision would inherit the
        guess with nothing recording that a guess was made.
"""

from app.domain.recovered_architecture import ArchitectureStyle, RecoveredArchitecture

from ...models import ObservedFact
from .._identity import fact_id
from .base import base_attributes, classify_label


class GenericAdapter:
    """Style-independent reduction, with the uncertainty recorded."""

    style = ArchitectureStyle.UNKNOWN

    def normalise(self, architecture: RecoveredArchitecture) -> tuple[ObservedFact, ...]:
        facts = []
        for relationship in architecture.relationships:
            source = architecture.element_by_id(relationship.source_id)
            target = architecture.element_by_id(relationship.target_id)
            if source is None or target is None:
                continue

            kind = classify_label(relationship.label)
            facts.append(
                ObservedFact(
                    fact_id=fact_id(source.name, kind, target.name, architecture.release_id),
                    release_id=architecture.release_id,
                    subject=source.name,
                    relationship=kind,
                    object=target.name,
                    style_resolved="generic",
                    quality=relationship.quality,
                    attributes=base_attributes(
                        relationship.label,
                        {"style_not_resolved": True, **relationship.attributes},
                    ),
                )
            )
        return tuple(facts)
