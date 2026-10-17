"""DetectionService: one release in, its metrics and anti-pattern instances out."""

import pytest

from app.components.degradation_detection.config import C3Config
from app.components.degradation_detection.detection import DetectionService
from app.components.degradation_detection.detection.metric_registry import MetricRegistry
from app.components.degradation_detection.detection.registry import ALL_DETECTORS
from app.components.degradation_detection.models import ReleaseDetection
from app.domain.release_package import ArchitectureStyle
from tests.components.degradation_detection.detection.graphs import TWO_TRIANGLES, release

UNIVERSAL = (
    "CyclicDependency",
    "HubLikeElement",
    "UnstableDependency",
    "OversizedElement",
    "BigBallOfMud",
)


def system(result: ReleaseDetection) -> dict[str, float | None]:
    return {o.metric: o.value for o in result.observations if o.element_id is None}


def test_detect_returns_every_declared_metric_for_the_release() -> None:
    cfg = C3Config()
    registry = MetricRegistry.from_config(
        cfg.metrics, anti_pattern_types=[d.id for d in ALL_DETECTORS]
    )

    result = DetectionService(cfg).detect(release("abcdef", TWO_TRIANGLES, release_id="v1.2.0"))

    assert isinstance(result, ReleaseDetection)
    assert result.release_id == "v1.2.0"
    expected = 6 * len(registry.element_metrics) + len(registry.system_metrics)
    assert len(result.observations) == expected
    assert [o.metric for o in result.observations if o.element_id is None] == [
        d.name for d in registry.system_metrics
    ]


def test_detect_runs_the_universal_detectors() -> None:
    # Two triangles joined by c -> d: two cycles, modularity 2*(3/7 - 1/4) = 0.36 (not mud), no
    # hub. The bridge makes c less stable (2/3) and d more stable (1/3) than their neighbours
    # (1/2), so b -> c and d -> e are unstable dependencies.
    result = DetectionService(C3Config()).detect(release("abcdef", TWO_TRIANGLES))

    assert [(i.anti_pattern_type, i.members) for i in result.instances] == [
        ("CyclicDependency", ("a", "b", "c")),
        ("CyclicDependency", ("d", "e", "f")),
        ("UnstableDependency", ("b",)),
        ("UnstableDependency", ("d",)),
    ]


def test_detect_keeps_null_metrics_null() -> None:
    result = DetectionService(C3Config()).detect(release(["a", "b", "lonely"], [("a", "b")]))

    [instability] = [
        o.value
        for o in result.observations
        if o.metric == "instability" and o.element_id == "lonely"
    ]
    assert instability is None


# --- registry: which detectors ran, and the anti-pattern counts -------------------------------


def test_without_datastore_access_shared_persistence_is_skipped_and_its_count_is_null() -> None:
    # The triangles plus an isolated g: same instances, and 6 of 7 elements are in one.
    result = DetectionService(C3Config()).detect(release("abcdefg", TWO_TRIANGLES))

    assert result.detectors_run == UNIVERSAL
    assert {k: v for k, v in system(result).items() if k.startswith("ap_")} == {
        "ap_count.CyclicDependency": 2.0,
        "ap_count.HubLikeElement": 0.0,
        "ap_count.UnstableDependency": 2.0,
        "ap_count.OversizedElement": 0.0,
        "ap_count.BigBallOfMud": 0.0,
        "ap_count.SharedPersistence": None,
        "ap_involvement_share": pytest.approx(6 / 7),
    }


def test_microservices_with_datastore_access_run_shared_persistence() -> None:
    r = release("abc", [("a", "b")], datastore_access=[("a", "db"), ("c", "db")])

    result = DetectionService(C3Config()).detect(r)

    assert result.detectors_run == (*UNIVERSAL, "SharedPersistence")
    assert [(i.anti_pattern_type, i.members) for i in result.instances] == [
        ("SharedPersistence", ("a", "c"))
    ]
    assert system(result)["ap_count.SharedPersistence"] == 1.0


def test_other_styles_never_run_shared_persistence() -> None:
    r = release(
        "abc", style=ArchitectureStyle.MONOLITH, datastore_access=[("a", "db"), ("c", "db")]
    )

    result = DetectionService(C3Config()).detect(r)

    assert result.detectors_run == UNIVERSAL
    assert result.instances == ()
    assert system(result)["ap_count.SharedPersistence"] is None
