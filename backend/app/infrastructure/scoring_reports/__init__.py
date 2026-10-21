# C4's saved reports on the local filesystem, read by the degradation scoring API, and the
# hand-over files degradation detection leaves for scoring.

from app.infrastructure.scoring_reports.detection_handover import DetectionHandoverFiles
from app.infrastructure.scoring_reports.file_store import ScoringReportFileStore

__all__ = ["DetectionHandoverFiles", "ScoringReportFileStore"]
