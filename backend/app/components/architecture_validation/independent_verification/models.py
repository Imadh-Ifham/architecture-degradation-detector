"""Independent verification data model.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Shapes used only inside this subcomponent. Anything shared with another
    subcomponent belongs in the component's own models.py.
"""

from dataclasses import dataclass


MECHANISM_CRITICAL_REFRAMING = "critical-reframing"


@dataclass(frozen=True)
class VerificationRequest:
    """One verdict posed back as a challenge.

    The verifier is shown the verdict deliberately. A verifier that does not
    see it is running the same task twice, which measures the model's
    self-consistency rather than verifying anything - and at temperature zero
    it would mostly agree with itself.
    """

    fact_id: str
    verdict: str
    reasoning: str
    evidence_hash: str
    mechanism: str = MECHANISM_CRITICAL_REFRAMING
