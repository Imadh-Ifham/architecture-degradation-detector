"""DetectionService: one release in, its metrics and anti-pattern instances out."""

import pytest

from app.components.degradation_detection.config import C3Config
from app.components.degradation_detection.detection import DetectionService
from app.components.degradation_detection.detection.metric_registry import MetricRegistry
from app.components.degradation_detection.detection.models import AntiPatternDetector
from app.components.degradation_detection.detection.registry import (
    ALL_DETECTORS,
    DetectorRegistry,
)
from app.components.degradation_detection.models import DetectorInfo, MetricLevel, ReleaseDetection
from app.domain.degradation_event import Scope, Worsening
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


# --- describe: what M4 needs to know about the metrics and detectors -------------------------


def test_describe_lists_the_declared_metrics_with_their_directions() -> None:
    cfg = C3Config()
    registry = MetricRegistry.from_config(
        cfg.metrics, anti_pattern_types=[d.id for d in ALL_DETECTORS]
    )

    catalog = DetectionService(cfg).describe()

    assert catalog.metrics == (*registry.element_metrics, *registry.system_metrics)
    assert catalog.metric(MetricLevel.SYSTEM, "modularity").worsening is Worsening.DECREASE
    assert catalog.metric(MetricLevel.ELEMENT, "instability").worsening is None


def test_describe_lists_every_catalog_detector_with_what_drives_it() -> None:
    catalog = DetectionService(C3Config()).describe()

    assert [d.anti_pattern_type for d in catalog.detectors] == [*UNIVERSAL, "SharedPersistence"]
    cyclic = catalog.detector("CyclicDependency")
    assert cyclic == DetectorInfo(
        anti_pattern_type="CyclicDependency",
        catalog="universal",
        scope=Scope.INSTANCE,
        driving_metrics=("scc_size",),
        instance_measures=ALL_DETECTORS[0].instance_measures,
    )
    assert cyclic.measure("member_count").worsening is Worsening.INCREASE


def test_describe_follows_the_registry_it_was_given() -> None:
    only_cycles = DetectorRegistry(ALL_DETECTORS, {"*": ("CyclicDependency",)})

    catalog = DetectionService(C3Config(), only_cycles).describe()

    assert [d.anti_pattern_type for d in catalog.detectors] == ["CyclicDependency"]
    assert [m.name for m in catalog.metrics if m.name.startswith("ap_count.")] == [
        "ap_count.CyclicDependency"
    ]


def test_unknown_metric_or_detector_is_an_error() -> None:
    catalog = DetectionService(C3Config()).describe()

    with pytest.raises(KeyError, match="not declared"):
        catalog.metric(MetricLevel.ELEMENT, "modularity")  # a system metric
    with pytest.raises(KeyError, match="not in the catalog"):
        catalog.detector("GodClass")
    with pytest.raises(KeyError, match="not an instance measure"):
        catalog.detector("CyclicDependency").measure("scc_size")


@pytest.mark.parametrize("detector", ALL_DETECTORS, ids=[d.id for d in ALL_DETECTORS])
def test_detector_declarations_agree_with_the_metric_registry(
    detector: AntiPatternDetector,
) -> None:
    """A driving metric must exist, and a measure named like a registry metric must mean it."""
    cfg = C3Config()
    registry = MetricRegistry.from_config(cfg.metrics, anti_pattern_types=[detector.id])
    declared = {d.name: d for d in (*registry.element_metrics, *registry.system_metrics)}

    assert set(detector.driving_metrics) <= set(declared)
    for measure in detector.instance_measures:
        assert measure.level is MetricLevel.INSTANCE
        assert measure.worsening is not None, "M4 tests every instance measure"
        if measure.name in declared:
            assert (measure.unit, measure.worsening) == (
                declared[measure.name].unit,
                declared[measure.name].worsening,
            )
