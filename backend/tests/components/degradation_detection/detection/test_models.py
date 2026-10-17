"""ReleaseContext: one release's metric values, as the detectors read them."""

import pytest

from app.components.degradation_detection.config import DetectionConfig
from app.components.degradation_detection.detection.models import ReleaseContext
from app.components.degradation_detection.models import MetricObservation


def obs(metric: str, value: float | None, element: str | None = None) -> MetricObservation:
    return MetricObservation(release_id="v1", element_id=element, metric=metric, value=value)


def test_context_indexes_observations_by_metric() -> None:
    ctx = ReleaseContext.from_observations(
        [
            obs("fan_in", 2.0, "a"),
            obs("fan_in", 0.0, "b"),
            obs("instability", None, "b"),
            obs("modularity", 0.4),
        ],
        DetectionConfig(),
    )

    assert ctx.element_values("fan_in") == {"a": 2.0, "b": 0.0}
    assert ctx.element_values("instability") == {"b": None}  # null stays null
    assert ctx.system_value("modularity") == 0.4


def test_context_refuses_a_metric_that_was_not_computed() -> None:
    ctx = ReleaseContext.from_observations([obs("fan_in", 1.0, "a")], DetectionConfig())

    with pytest.raises(KeyError, match="fan_out"):
        ctx.element_values("fan_out")
    with pytest.raises(KeyError, match="modularity"):
        ctx.system_value("modularity")
