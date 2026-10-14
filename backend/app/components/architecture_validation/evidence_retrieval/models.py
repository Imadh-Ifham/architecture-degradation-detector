"""Evidence retrieval data model.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Shapes used only inside this subcomponent. Anything shared with another
    subcomponent belongs in the component's own models.py.
"""

from dataclasses import dataclass

from ..models import EvidenceRole


@dataclass(frozen=True)
class RetrievalBudget:
    """What a package is allowed to cost.

    The free model tier limits tokens per minute rather than requests, so
    package size, not call count, is what decides whether a whole release can
    be validated inside a demo slot.

    When the budget is exceeded, items are dropped from the weakest role
    upward in `drop_order` - never at random, because non-deterministic
    truncation would change the evidence hash between runs and silently miss
    the cache.
    """

    max_characters: int = 12_000
    max_neighbours: int = 8
    drop_order: tuple[EvidenceRole, ...] = (
        EvidenceRole.STRUCTURAL_CONTEXT,
        EvidenceRole.IMPLICATION,
        EvidenceRole.SUPERSEDED,
        EvidenceRole.RATIONALE,
    )
