"""Validation reasoning data model.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Shapes used only inside this subcomponent. Anything shared with another
    subcomponent belongs in the component's own models.py.
"""

from dataclasses import dataclass

from ..models import GuardFailure


@dataclass(frozen=True)
class GuardOutcome:
    """The result of running the guards over one response.

    A rejected response is retried exactly once with identical input, then
    becomes insufficient evidence. It never becomes a verdict: a system that
    answers when it is confused produces output indistinguishable from output
    it is sure about.
    """

    accepted: bool
    failure: GuardFailure | None = None
    refs_at_fault: tuple[str, ...] = ()
    """The citations the rejection is about.

    Named for the fault rather than for one guard's version of it, because
    they are not always references that failed to resolve: guard C's are real
    items that cannot carry a conclusion, and guard D's is the decision that
    was replaced. Carried at all because *a citation was wrong* cannot be told
    apart from *the model invented a document* without them.
    """
