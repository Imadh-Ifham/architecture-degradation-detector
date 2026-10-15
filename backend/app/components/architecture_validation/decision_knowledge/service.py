"""Decision knowledge service.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Holds the decision history and answers which decision governed at a release.

    Research module: M2.
"""

from ..models import ObservedFact, Resolution


class DecisionKnowledgeService:
    """Holds the decision history and answers which decision governed at a release."""

    def resolve(self, fact: ObservedFact) -> Resolution:
        """Resolves which decision governs a fact at the fact's release.

        Reads an append-only event log and replays it into an index of
        half-open validity intervals, so the answer to "what applied at this
        release" stays correct after a later decision supersedes an earlier
        one.

        Returns ambiguity rather than resolving it when two decisions apply and
        neither supersedes the other: an invented tiebreak cannot be shown to
        be right.
        """

        raise NotImplementedError
