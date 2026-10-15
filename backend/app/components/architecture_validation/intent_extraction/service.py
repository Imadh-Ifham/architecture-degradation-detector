"""Intent extraction service.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Reads architectural intent out of whatever the repository actually contains.

    Research module: new.
"""

from .models import ExtractionOutcome


class IntentExtractionService:
    """Reads architectural intent out of whatever the repository actually contains."""

    def extract(self, repository_id: str, release_id: str) -> ExtractionOutcome:
        """Extracts candidate decisions from every registered intent source.

        Most repositories hold no decision records, so intent has to be read
        from what they do hold: network policies, service contracts, release
        notes. Each source is an adapter behind one protocol, and each
        candidate carries the tier it came from.

        The tier travels with the candidate because a weak source must not be
        able to produce a confident accusation downstream.
        """

        raise NotImplementedError
