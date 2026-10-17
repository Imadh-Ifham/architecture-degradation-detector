"""M1 step 5: the validation-confidence gate [D-07]. Boundaries belong to the higher status."""

import pytest

from app.components.degradation_detection.config import GateConfig
from app.components.degradation_detection.ingestion.gate import gate
from app.domain.canonical_release import GateStatus

CFG = GateConfig()


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [
        (1.0, GateStatus.ACCEPTED),
        (0.70, GateStatus.ACCEPTED),
        (0.6999, GateStatus.DOWNWEIGHTED),
        (0.60, GateStatus.DOWNWEIGHTED),
        (0.50, GateStatus.DOWNWEIGHTED),
        (0.4999, GateStatus.EXCLUDED),
        (0.0, GateStatus.EXCLUDED),
    ],
)
def test_gate_boundaries(confidence: float, expected: GateStatus) -> None:
    assert gate(confidence, CFG) is expected


def test_gate_thresholds_come_from_config() -> None:
    strict = GateConfig(accept=0.95, exclude=0.90)

    assert gate(0.92, strict) is GateStatus.DOWNWEIGHTED
    assert gate(0.70, strict) is GateStatus.EXCLUDED
