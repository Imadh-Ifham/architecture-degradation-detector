"""Architect review service.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Queues what the system will not decide alone, and records what a person decided.

    Research module: M7.
"""

from ..models import ClassifiedFact


class ArchitectReviewService:
    """Queues what the system will not decide alone, and records what a person decided."""

    def enqueue(self, facts: tuple[ClassifiedFact, ...]) -> tuple[str, ...]:
        """Places facts needing human judgement on the review queue.

        Writes a row and renders nothing: the review surface belongs to the
        frontend, and a subcomponent that produced HTML would be impossible to
        test without one.

        A confirmed candidate is appended to the knowledge log as an event, so
        the fact revalidates against a ratified decision on the next run. That
        loop is what turns weak evidence into strong evidence rather than into
        a dead end.
        """

        raise NotImplementedError
