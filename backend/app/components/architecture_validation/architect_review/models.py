"""Architect review data model.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Shapes used only inside this subcomponent. Anything shared with another
    subcomponent belongs in the component's own models.py.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

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


class ReviewStatus(StrEnum):
    """Where one queued fact has got to.

    Three values and not a workflow. No claiming, no reassignment, no due
    date: one table, one drill-in, one decision. A fourth value here would be
    the first step of a process this component has no business running.
    """

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ReviewOutcome:
    """What recording one decision did.

    `ratified` is how many decision versions the confirmation applied to, and
    it is carried out of the component rather than logged: a confirmation that
    matched no open record has to be visible to whoever pressed the button,
    not discovered later in a replay.

    Zero on a rejection, always. A rejection ratifies nothing and appends
    nothing - the item records it, which is the part that matters.
    """

    item_id: str
    status: ReviewStatus
    ratified: int
