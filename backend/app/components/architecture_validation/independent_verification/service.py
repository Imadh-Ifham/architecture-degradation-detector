"""Independent verification service.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Re-examines a verdict as a challenge to it, using a different model.

    Research module: M5.
"""

from ..models import EvidencePackage, PrimaryVerdict, Verification


class IndependentVerificationService:
    """Re-examines a verdict as a challenge to it, using a different model."""

    def verify(self, verdict: PrimaryVerdict, package: EvidencePackage) -> Verification:
        """Challenges a primary verdict against the same evidence.

        Poses the verdict back as something to find fault with, using a
        different model from the reasoner - which costs nothing on open-weights
        providers and is the difference between a check and a second opinion
        from the same source.

        Records the mechanism used, so results from different weeks stay
        comparable when the mechanism itself becomes the subject of study.

        Can only lower an outcome, never raise one. The verifier saw the same
        evidence, so agreement says something about the models rather than
        about the architecture.
        """

        raise NotImplementedError
