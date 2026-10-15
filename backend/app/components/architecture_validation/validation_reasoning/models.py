"""Validation reasoning data model.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Shapes used only inside this subcomponent. Anything shared with another
    subcomponent belongs in the component's own models.py.
"""

from dataclasses import dataclass
from enum import StrEnum


class GuardFailure(StrEnum):
    """Why a model response was rejected.

    Recorded rather than collapsed into a single error, because the two
    failures mean different things: a malformed response is a schema or
    provider problem, and a citation that resolves to nothing is the model
    inventing evidence.
    """

    MALFORMED = "malformed"
    UNRESOLVED_CITATION = "unresolved_citation"
    NO_CITATION = "no_citation"


@dataclass(frozen=True)
class GuardOutcome:
    """The result of running both guards over one response.

    A rejected response is retried exactly once with identical input, then
    becomes insufficient evidence. It never becomes a verdict: a system that
    answers when it is confused produces output indistinguishable from output
    it is sure about.
    """

    accepted: bool
    failure: GuardFailure | None = None
    unresolved_refs: tuple[str, ...] = ()
