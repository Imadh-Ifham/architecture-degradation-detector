"""M2 Anti-Pattern Detection Engine (plan Section 4, M2).

Per release: build the graph, compute every metric the registry declares, choose the detectors
for the release's architecture style (``registry.py``, the only style branch in C3), run them
over the graph and those metrics, then count what they found. Each release is analysed on its
own; M3 joins releases together.
"""

from app.components.degradation_detection.config import C3Config
from app.components.degradation_detection.detection.graph_builder import build_graph
from app.components.degradation_detection.detection.metric_registry import MetricRegistry
from app.components.degradation_detection.detection.metrics import (
    compute_metrics,
    count_anti_patterns,
)
from app.components.degradation_detection.detection.models import ReleaseContext
from app.components.degradation_detection.detection.registry import DetectorRegistry
from app.components.degradation_detection.models import ReleaseDetection
from app.domain.canonical_release import CanonicalRelease


class DetectionService:
    def __init__(self, cfg: C3Config, detectors: DetectorRegistry | None = None) -> None:
        """``detectors`` defaults to the catalog in ``cfg``; tests pass an extended one."""
        self._cfg = cfg
        self._detectors = detectors or DetectorRegistry.from_catalog(cfg.catalog)
        self._metrics = MetricRegistry.from_config(
            cfg.metrics, anti_pattern_types=self._detectors.detector_ids
        )

    def detect(self, release: CanonicalRelease) -> ReleaseDetection:
        """Metrics and anti-pattern instances of one release."""
        graph = build_graph(release)
        observations = compute_metrics(graph, self._metrics)
        ctx = ReleaseContext.from_observations(observations, self._cfg.detection)
        detectors = self._detectors.for_release(release)
        instances = tuple(
            instance for detector in detectors for instance in detector.detect(graph, ctx)
        )
        ran = tuple(detector.id for detector in detectors)
        return ReleaseDetection(
            release_id=release.release_id,
            observations=observations + count_anti_patterns(graph, self._metrics, ran, instances),
            instances=instances,
            detectors_run=ran,
        )
