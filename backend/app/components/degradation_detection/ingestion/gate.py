"""M1 step 5: the validation-confidence gate [D-07] (pure).

C2 states how confident it is in each release. A release C2 doubts is still worth keeping
(DOWNWEIGHTED: included in the timeline and listed on every event that spans it); one it barely
trusts is stored for the record but kept out of the analysis (EXCLUDED). A boundary value
belongs to the higher status: confidence 0.70 is ACCEPTED, 0.50 is DOWNWEIGHTED.
"""

from app.components.degradation_detection.config import GateConfig
from app.domain.canonical_release import GateStatus


def gate(confidence: float, cfg: GateConfig) -> GateStatus:
    if confidence >= cfg.accept:
        return GateStatus.ACCEPTED
    if confidence >= cfg.exclude:
        return GateStatus.DOWNWEIGHTED
    return GateStatus.EXCLUDED
