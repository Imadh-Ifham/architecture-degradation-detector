"""HubLikeElement: fan-in and fan-out both above the release's upper IQR fence."""

from app.components.degradation_detection.config import DetectionConfig, HubConfig
from app.components.degradation_detection.detection.universal.hub_like_element import (
    HubLikeElement,
)
from app.domain.degradation_event import Scope
from tests.components.degradation_detection.detection.graphs import release
from tests.components.degradation_detection.detection.universal.run import run

DETECTOR = HubLikeElement()

SOURCES = [f"s{i}" for i in range(1, 7)]
TARGETS = [f"t{i}" for i in range(1, 7)]
STAR = release(["h", *SOURCES, *TARGETS], [(s, "h") for s in SOURCES] + [("h", t) for t in TARGETS])


def test_declaration() -> None:
    assert DETECTOR.id == "HubLikeElement"
    assert DETECTOR.catalog == "universal"
    assert DETECTOR.styles == frozenset({"*"})
    assert DETECTOR.scope is Scope.ELEMENT
    assert DETECTOR.required_fields == frozenset()
    assert DETECTOR.driving_metrics == ("fan_in_norm", "fan_out_norm")
    assert DETECTOR.instance_measures == ("degree",)


def test_star_centre_is_a_hub() -> None:
    [hub] = run(STAR, [DETECTOR])

    assert hub.members == ("h",)
    assert hub.local_instance_id == "HubLikeElement:h"
    assert hub.measures == {"degree": 12.0}


def test_fence_multiplier_comes_from_config() -> None:
    # Fences are 1 + k * 1; h has 6 in and 6 out. k = 5 puts the fence at 6, and 6 is not above.
    strict = DetectionConfig(hub=HubConfig(iqr_k=5))

    assert run(STAR, [DETECTOR], cfg=strict) == []
    assert len(run(STAR, [DETECTOR], cfg=DetectionConfig(hub=HubConfig(iqr_k=4.9)))) == 1


def test_single_element_release_has_no_hub() -> None:
    assert run(release(["only"]), [DETECTOR]) == []
