"""M3 Cross-Release Aligner (plan Section 4, M3).

T-08: element alignment between consecutive releases and the lineages it produces. T-09:
anti-pattern instance tracks over those lineages. The series builder (T-10) extends ``track``.

The rule throughout: when unsure, break the series rather than guess. A missed link shortens a
series; a wrong one joins two histories and can invent a trend with a real p-value.
"""

from collections.abc import Sequence

from app.components.degradation_detection.config import C3Config
from app.components.degradation_detection.models import ReleaseDetection, Timeline
from app.components.degradation_detection.tracking.element_alignment import align_timeline
from app.components.degradation_detection.tracking.instances import track_instances
from app.components.degradation_detection.tracking.lineage import build_lineages
from app.components.degradation_detection.tracking.models import TrackingResult


class TrackingService:
    def __init__(self, cfg: C3Config) -> None:
        self._cfg = cfg

    def track(self, timeline: Timeline, detections: Sequence[ReleaseDetection]) -> TrackingResult:
        """Element lineages, their rename events and alignment decisions, and instance tracks.

        ``detections[k]`` is M2's output for ``timeline.entries[k]``.
        """
        pairs = align_timeline((entry.release for entry in timeline.entries), self._cfg.align)
        lineages, events = build_lineages(timeline, pairs)
        return TrackingResult(
            system_id=timeline.system_id,
            lineages=lineages,
            events=events,
            decisions=tuple(decision for pair in pairs for decision in pair.decisions),
            tracks=track_instances(timeline, detections, lineages, self._cfg.tracking),
        )
