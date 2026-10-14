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
from .base import classify_label, observed_fact


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

            facts.append(
                observed_fact(
                    architecture,
                    subject=source,
                    relationship=classify_label(relationship.label),
                    object_=target,
                    style_resolved="generic",
                    quality=relationship.quality,
                    label=relationship.label,
                    extra={"style_not_resolved": True, **relationship.attributes},
                )
            )
        return tuple(facts)
