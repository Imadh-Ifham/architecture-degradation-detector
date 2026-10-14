"""Architect review data model.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Shapes used only inside this subcomponent. Anything shared with another
    subcomponent belongs in the component's own models.py.
"""

from dataclasses import dataclass
from datetime import datetime


EVENT_DECISION_CONFIRMED = "DECISION_CONFIRMED"
EVENT_DECISION_REVOKED = "DECISION_REVOKED"


@dataclass(frozen=True)
class ReviewDecision:
    """What an architect decided about one queued fact.

    A reversal is appended as its own event rather than editing or deleting the
    confirmation. The log has to be able to answer what the system believed at
    a past moment, and a record that can be deleted makes that unanswerable.

    `decided_by` names a role rather than a person: the role exists in the
    system and whoever fills it is interchangeable.
    """

    item_id: str
    accepted: bool
    decided_by: str
    decided_at: datetime
    note: str | None = None

    @property
    def event_type(self) -> str:
        return EVENT_DECISION_CONFIRMED if self.accepted else EVENT_DECISION_REVOKED
