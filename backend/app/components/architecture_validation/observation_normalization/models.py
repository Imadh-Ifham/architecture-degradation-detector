"""Observation normalization data model.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Shapes used only inside this subcomponent. Anything shared with another
    subcomponent belongs in the component's own models.py.
"""

from dataclasses import dataclass, field

from ..models import ObservedFact


@dataclass(frozen=True)
class NormalizationOutcome:
    """The facts for one release, and how they were arrived at.

    `style_resolved` and `derived_relationships` are reported rather than
    inferred later: a run whose edges were derived rather than recovered, or
    whose style could not be determined, has to say so, because both cap how
    strong any verdict about it may become.
    """

    facts: tuple[ObservedFact, ...]
    style_resolved: str
    derived_relationships: int = 0
    warnings: tuple[str, ...] = field(default_factory=tuple)
