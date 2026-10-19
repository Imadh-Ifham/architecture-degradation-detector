"""The synthetic stub through M1 -> M4, in memory, for the acceptance tests of T-12 and later.

Computed once per test session (``cache``): it runs 20000-shuffle permutation tests.
"""

from dataclasses import dataclass
from functools import cache

from app.components.degradation_detection.config import C3Config
from app.components.degradation_detection.detection import DetectionService
from app.components.degradation_detection.ingestion import IngestService
from app.components.degradation_detection.ingestion.models import RawPackage
from app.components.degradation_detection.models import DetectionCatalog, Timeline
from app.components.degradation_detection.stub import StubService
from app.components.degradation_detection.stub.models import GroundTruth
from app.components.degradation_detection.tracking import TrackingService
from app.components.degradation_detection.tracking.models import TrackingResult
from app.components.degradation_detection.trends import TrendService
from app.components.degradation_detection.trends.models import TrendAnalysis
from tests.components.degradation_detection.fakes import FixedClock, InMemoryReleaseRepository


@dataclass(frozen=True)
class StubRun:
    cfg: C3Config
    truth: GroundTruth
    timeline: Timeline
    catalog: DetectionCatalog
    tracking: TrackingResult
    analysis: TrendAnalysis


def stub_packages() -> list[RawPackage]:
    """The stub's release packages (the hotfix that M1 rejects included), sorted by file name."""
    return [
        RawPackage(source=name, data=text.encode("utf-8"))
        for name, text in sorted(StubService().generate().system_files.items())
        if name.endswith(".json")
    ]


def ingested_stub(cfg: C3Config | None = None) -> InMemoryReleaseRepository:
    """A fresh in-memory release store holding the ingested stub."""
    repo = InMemoryReleaseRepository()
    IngestService(repo, FixedClock(), cfg or C3Config()).ingest(stub_packages())
    return repo


@cache
def stub_run() -> StubRun:
    cfg = C3Config()
    stub = StubService().generate()
    ingest = IngestService(ingested_stub(cfg), FixedClock(), cfg)
    timeline = ingest.timeline(stub.ground_truth.system_id)
    detection = DetectionService(cfg)
    tracking = TrackingService(cfg).track(
        timeline, [detection.detect(entry.release) for entry in timeline.entries]
    )
    catalog = detection.describe()
    analysis = TrendService(cfg).analyze(
        timeline, tracking.series, tracking.lineages, tracking.tracks, catalog
    )
    return StubRun(cfg, stub.ground_truth, timeline, catalog, tracking, analysis)
