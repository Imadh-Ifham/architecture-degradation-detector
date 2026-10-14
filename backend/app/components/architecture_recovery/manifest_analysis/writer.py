"""Manifest analysis writer.

Author: Imadh Ifham
Date: 2026-10-14
Description:
    Serialises an analysis report to `manifest_analysis.json`. Written through a
    temporary file and renamed into place, so a reader or a crash never observes
    a partially written report.
"""

import json
import os
import uuid
from pathlib import Path

from app.components.architecture_recovery.manifest_analysis.errors import (
    AnalysisWriteError,
)
from app.components.architecture_recovery.manifest_analysis.models import (
    ManifestAnalysisReport,
)


MANIFEST_ANALYSIS_FILE_NAME = "manifest_analysis.json"


def write_manifest_analysis(report: ManifestAnalysisReport, directory: Path) -> Path:
    """Write `report` into `directory` and return the file path.

    Raises `AnalysisWriteError` if the file cannot be written.
    """

    directory = Path(directory)

    try:
        directory.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
        target = directory / MANIFEST_ANALYSIS_FILE_NAME
        temporary = directory / f".{MANIFEST_ANALYSIS_FILE_NAME}.{uuid.uuid4().hex}.tmp"

        temporary.write_text(payload + "\n", encoding="utf-8")

        # Atomic rename within the same directory: the report is either the
        # previous version or the new one, never a truncated mix.
        os.replace(temporary, target)

        return target
    except OSError as error:
        raise AnalysisWriteError(
            f"Could not write the analysis report into '{directory}': {error}"
        ) from error


def load_manifest_analysis(path: Path) -> dict:
    """Read an analysis report back from disk."""

    return json.loads(Path(path).read_text(encoding="utf-8"))
