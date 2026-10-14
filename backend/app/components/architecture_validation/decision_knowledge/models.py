"""Decision knowledge data model.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Shapes used only inside this subcomponent. Anything shared with another
    subcomponent belongs in the component's own models.py.
"""

from dataclasses import dataclass

from ..models import DecisionRecord


@dataclass(frozen=True)
class DecisionVersion:
    """One decision over one release range, as held in the index.

    The range is half-open, so a decision and the decision superseding it never
    both apply to the same release.
    """

    record: DecisionRecord
    valid_from: str
    valid_to: str | None

    def covers(self, release_id: str) -> bool:
        """Whether this version was in force at `release_id`.

        Comparison is left to the caller, which parses release identifiers into
        ordered versions. String comparison would be wrong here: "v2.10.0" sorts
        below "v2.9.0".
        """

        raise NotImplementedError


@dataclass(frozen=True)
class KnowledgeEvent:
    """One entry in the append-only log."""

    event_type: str
    payload: dict
    recorded_at: str
