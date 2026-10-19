"""Dependency resolution writer.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Serialises a dependency resolution report to `dependency_resolution.json`,
    alongside the inventory, manifest-analysis and component-discovery
    artifacts. Written through a temporary file and renamed into place, so a
    reader or a crash never observes a partially written report.
"""

import json
import os
import uuid
from pathlib import Path

from app.components.architecture_recovery.dependency_resolution.errors import (
    DependencyResolutionWriteError,
)
from app.components.architecture_recovery.dependency_resolution.models import (
    DependencyResolutionReport,
)

DEPENDENCY_RESOLUTION_FILE_NAME = "dependency_resolution.json"


def write_dependency_resolution(
    report: DependencyResolutionReport, directory: Path
) -> Path:
    """Write `report` into `directory` and return the file path.

    Raises `DependencyResolutionWriteError` if the file cannot be written.
    """

    directory = Path(directory)

    try:
        directory.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
        target = directory / DEPENDENCY_RESOLUTION_FILE_NAME
        temporary = directory / f".{DEPENDENCY_RESOLUTION_FILE_NAME}.{uuid.uuid4().hex}.tmp"

        temporary.write_text(payload + "\n", encoding="utf-8")

        # Atomic rename within the same directory: the report is either the
        # previous version or the new one, never a truncated mix of both.
        os.replace(temporary, target)

        return target
    except OSError as error:
        raise DependencyResolutionWriteError(
            f"Could not write the dependency resolution report into '{directory}': "
            f"{error}"
        ) from error


def load_dependency_resolution(path: Path) -> dict:
    """Read a dependency resolution report back from disk."""

    return json.loads(Path(path).read_text(encoding="utf-8"))
