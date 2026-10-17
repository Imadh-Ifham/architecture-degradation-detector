"""M4 Trend Analyzer (plan Section 4, M4): is each anti-pattern getting worse?

Every series of the run is tested (Mann-Kendall + Sen's slope, ``analyzer.py``), the run is one
Benjamini-Hochberg family, and the significant worsening trends are assembled into event
candidates by scope (``candidates.py``). A fixed threshold never decides degradation: a trend
does [locked decision 2].

Everything M4 needs from the other subcomponents is passed in by the component service: the
timeline (M1), the declarations of metrics and detectors (M2 ``describe()``), and the series,
lineages and instance tracks (M3).
"""

from collections.abc import Sequence

from app.components.degradation_detection.config import C3Config
from app.components.degradation_detection.models import (
    DetectionCatalog,
    InstanceTrack,
    Lineage,
    Series,
    Timeline,
)
from app.components.degradation_detection.trends.analyzer import analyze_series, metric_def
from app.components.degradation_detection.trends.candidates import assemble_candidates
from app.components.degradation_detection.trends.models import TrendAnalysis


class TrendService:
    def __init__(self, cfg: C3Config) -> None:
        self._cfg = cfg

    def analyze(
        self,
        timeline: Timeline,
        series: Sequence[Series],
        lineages: Sequence[Lineage],
        tracks: Sequence[InstanceTrack],
        catalog: DetectionCatalog,
    ) -> TrendAnalysis:
        """Every tested series with its result, the untested ones, and the event candidates."""
        track_types = {track.track_id: track.anti_pattern_type for track in tracks}
        results, untested = analyze_series(
            [(s, metric_def(s, catalog, track_types)) for s in series], self._cfg.trend
        )
        return TrendAnalysis(
            results=results,
            untested=untested,
            candidates=assemble_candidates(results, timeline, lineages, tracks, catalog),
        )
