"""Run detectors on a test release the way DetectionService does: graph -> metrics -> context."""

from collections.abc import Iterable

from app.components.degradation_detection.config import C3Config, DetectionConfig
from app.components.degradation_detection.detection.graph_builder import build_graph
from app.components.degradation_detection.detection.metric_registry import MetricRegistry
from app.components.degradation_detection.detection.metrics import compute_metrics
from app.components.degradation_detection.detection.models import (
    AntiPatternDetector,
    ArchGraph,
    ReleaseContext,
)
from app.components.degradation_detection.detection.universal import UNIVERSAL_DETECTORS
from app.components.degradation_detection.models import AntiPatternInstance
from app.domain.canonical_release import CanonicalRelease


def prepare(
    r: CanonicalRelease, cfg: DetectionConfig | None = None
) -> tuple[ArchGraph, ReleaseContext]:
    graph = build_graph(r)
    observations = compute_metrics(graph, MetricRegistry.from_config(C3Config().metrics))
    return graph, ReleaseContext.from_observations(observations, cfg or DetectionConfig())


def run(
    r: CanonicalRelease,
    detectors: Iterable[AntiPatternDetector] = UNIVERSAL_DETECTORS,
    cfg: DetectionConfig | None = None,
) -> list[AntiPatternInstance]:
    graph, ctx = prepare(r, cfg)
    return [instance for detector in detectors for instance in detector.detect(graph, ctx)]
