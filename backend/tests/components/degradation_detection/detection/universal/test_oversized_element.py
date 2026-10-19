"""OversizedElement: robust z of size above the configured limit, within the release."""

from app.components.degradation_detection.config import DetectionConfig, OversizedConfig
from app.components.degradation_detection.detection.metric_registry import instance_measure
from app.components.degradation_detection.detection.universal.oversized_element import (
    OversizedElement,
)
from app.domain.degradation_event import Scope
from tests.components.degradation_detection.detection.graphs import release
from tests.components.degradation_detection.detection.universal.run import run

DETECTOR = OversizedElement()

# Median 3, MAD 1: size_rz(e) = 7 / 1.4826 = 4.72.
SIZES: dict[str, float | None] = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 10}


def test_declaration() -> None:
    assert DETECTOR.id == "OversizedElement"
    assert DETECTOR.catalog == "universal"
    assert DETECTOR.styles == frozenset({"*"})
    assert DETECTOR.scope is Scope.ELEMENT
    assert DETECTOR.required_fields == frozenset()
    assert DETECTOR.driving_metrics == ("size_rz",)
    assert DETECTOR.instance_measures == (instance_measure("size_rz", "robust_z"),)


def test_outlier_is_oversized() -> None:
    [instance] = run(release("abcde", sizes=SIZES), [DETECTOR])

    assert instance.members == ("e",)
    assert instance.local_instance_id == "OversizedElement:e"
    assert instance.measures["size_rz"] == 7 / 1.4826


def test_limit_is_strict_and_from_config() -> None:
    at = DetectionConfig(oversized=OversizedConfig(z_max=7 / 1.4826))

    assert run(release("abcde", sizes=SIZES), [DETECTOR], cfg=at) == []


def test_unknown_sizes_never_fire() -> None:
    assert run(release("abcde"), [DETECTOR]) == []
