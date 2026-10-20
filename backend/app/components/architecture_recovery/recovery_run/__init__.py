"""How one release's architecture was recovered, and what that produced.

Author: Imadh Ifham
Date: 2026-10-20
Description:
    A record of the run and a projection of its artifacts. The pipeline page
    shows that recovery ran; this is what lets a screen explain how.
"""

from .models import (
    RECOVERY_RUN_FILE,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_SKIPPED,
    StageRecord,
    StageTimer,
    build_run,
    now,
    read_run,
    write_run,
)
from .pipeline import RECOVERY_STAGES, STAGE_BY_NAME, RecoveryStage
from .report import build_report

__all__ = [
    "RECOVERY_RUN_FILE",
    "RECOVERY_STAGES",
    "STAGE_BY_NAME",
    "STATUS_COMPLETED",
    "STATUS_FAILED",
    "STATUS_SKIPPED",
    "RecoveryStage",
    "StageRecord",
    "StageTimer",
    "build_report",
    "build_run",
    "now",
    "read_run",
    "write_run",
]
