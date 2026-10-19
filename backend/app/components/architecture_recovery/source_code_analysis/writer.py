"""Source code analysis writer.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Serialises a source code analysis report to `source_code_analysis.json`,
    beside the inventory, manifest-analysis, component-discovery and
    dependency-resolution artifacts. Written through a temporary file and
    renamed into place, so a reader or a crash never observes a partial report.
"""

import json
import os
import uuid
from pathlib import Path

from app.components.architecture_recovery.source_code_analysis.errors import (
    SourceCodeAnalysisWriteError,
)
from app.components.architecture_recovery.source_code_analysis.models import (
    SourceCodeAnalysisReport,
)

SOURCE_CODE_ANALYSIS_FILE_NAME = "source_code_analysis.json"


def write_source_code_analysis(
    report: SourceCodeAnalysisReport, directory: Path
) -> Path:
    """Write `report` into `directory` and return the file path."""

    directory = Path(directory)

    try:
        directory.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
        target = directory / SOURCE_CODE_ANALYSIS_FILE_NAME
        temporary = directory / f".{SOURCE_CODE_ANALYSIS_FILE_NAME}.{uuid.uuid4().hex}.tmp"

        temporary.write_text(payload + "\n", encoding="utf-8")

        # Atomic rename within the same directory: the report is either the
        # previous version or the new one, never a truncated mix of both.
        os.replace(temporary, target)

        return target
    except OSError as error:
        raise SourceCodeAnalysisWriteError(
            f"Could not write the source code analysis report into '{directory}': "
            f"{error}"
        ) from error


def load_source_code_analysis(path: Path) -> dict:
    """Read a source code analysis report back from disk."""

    return json.loads(Path(path).read_text(encoding="utf-8"))
