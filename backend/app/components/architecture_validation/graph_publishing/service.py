"""Graph publishing service.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Publishes the validated architecture as a graph the next component reads.

    Research module: M8.
"""

from app.domain.recovered_architecture import RecoveredArchitecture

from ..models import ValidationRunResult


class GraphPublishingService:
    """Publishes the validated architecture as a graph the next component reads."""

    def publish(self, run: ValidationRunResult,
                architecture: RecoveredArchitecture) -> str:
        """Builds and publishes the validated architecture graph.

        Each verdict is attached to the relationship it describes, so the
        consumer never has to join a findings list back onto a topology - a
        join being a place where two sides can disagree about what the
        topology was.

        Every fact appears, including uncovered ones. An omitted fact would
        make the published graph quietly incomplete, and the consumer would
        compute over a subset without knowing it.
        """

        raise NotImplementedError
