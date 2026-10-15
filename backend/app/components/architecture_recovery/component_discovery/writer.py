"""Component discovery writer.

Author: Imadh Ifham
Date: 2026-10-15
Description:
    Serialises a discovery report to `component_discovery.json`, alongside the
    inventory and manifest-analysis artifacts. Written through a temporary file
    and renamed into place, so a reader or a crash never observes a partially
    written report.
"""

import json
import os
import uuid
from pathlib import Path

from app.components.architecture_recovery.component_discovery.errors import (
    DiscoveryWriteError,
)
from app.components.architecture_recovery.component_discovery.models import (
    ComponentDiscoveryReport,
)


COMPONENT_DISCOVERY_FILE_NAME = "component_discovery.json"


def write_component_discovery(
    report: ComponentDiscoveryReport, directory: Path
) -> Path:
    """Write `report` into `directory` and return the file path.

    Raises `DiscoveryWriteError` if the file cannot be written.
    """

    directory = Path(directory)

    try:
        directory.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
        target = directory / COMPONENT_DISCOVERY_FILE_NAME
        temporary = directory / f".{COMPONENT_DISCOVERY_FILE_NAME}.{uuid.uuid4().hex}.tmp"

        temporary.write_text(payload + "\n", encoding="utf-8")

        # Atomic rename within the same directory: the report is either the
        # previous version or the new one, never a truncated mix of both.
        os.replace(temporary, target)

        return target
    except OSError as error:
        raise DiscoveryWriteError(
            f"Could not write the component discovery report into '{directory}': "
            f"{error}"
        ) from error


def load_component_discovery(path: Path) -> dict:
    """Read a discovery report back from disk."""

    return json.loads(Path(path).read_text(encoding="utf-8"))
