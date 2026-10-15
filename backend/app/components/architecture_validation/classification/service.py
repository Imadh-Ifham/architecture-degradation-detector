"""Classification service.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Turns a verdict and its verification into a bucket, a confidence and a route.

    Research module: M6.
"""

from ..models import (
    ClassifiedFact,
    ObservedFact,
    PrimaryVerdict,
    Resolution,
    Verification,
)


class ClassificationService:
    """Turns a verdict and its verification into a bucket, a confidence and a route."""

    def classify(self, fact: ObservedFact, resolution: Resolution,
                 verdict: PrimaryVerdict | None,
                 verification: Verification | None) -> ClassifiedFact:
        """Assigns the final bucket, confidence and route for one fact.

        Two lookup tables and one threshold, all in plain code. The first maps
        a verdict to a bucket. The second caps the bucket by the strength of
        the source the decision came from, so weak evidence cannot produce a
        confident accusation.

        The ceiling is applied after the model has answered, not asked for in
        the prompt, so it holds even when the model is wrong.

        Emits the arithmetic behind the confidence value alongside it. A bare
        number invites one question that cannot otherwise be answered.
        """

        raise NotImplementedError
