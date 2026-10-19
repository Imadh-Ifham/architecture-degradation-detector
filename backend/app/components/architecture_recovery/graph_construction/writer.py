"""Graph construction report writer.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Writes `architecture_graph_construction.json` into a directory scoped by
    the snapshot id, so the report of one release can never overwrite the
    report of another. Written through a temporary file and renamed into place.
"""

import json
import os
import uuid
from pathlib import Path

from app.components.architecture_recovery.graph_construction.errors import (
    GraphConstructionWriteError,
)
from app.components.architecture_recovery.graph_construction.models import (
    GraphConstructionReport,
)

GRAPH_CONSTRUCTION_FILE_NAME = "architecture_graph_construction.json"
GRAPH_CONSTRUCTION_DIRECTORY = "graph_construction"


def snapshot_directory(workspace: Path, snapshot_id: str) -> Path:
    """Return the report directory for one snapshot.

    The colon that separates the id's prefix is not a legal filename character
    on Windows, so the id is reduced for the path only. The identifier stored
    inside the report is unchanged.
    """

    safe = "".join(
        character if character.isalnum() or character in "-._" else "-"
        for character in snapshot_id
    )

    return Path(workspace) / GRAPH_CONSTRUCTION_DIRECTORY / safe


def write_graph_construction(
    report: GraphConstructionReport, workspace: Path
) -> Path:
    """Write `report` under the workspace and return the file path."""

    directory = snapshot_directory(workspace, report.snapshot_id)

    try:
        directory.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
        target = directory / GRAPH_CONSTRUCTION_FILE_NAME
        temporary = directory / f".{GRAPH_CONSTRUCTION_FILE_NAME}.{uuid.uuid4().hex}.tmp"

        temporary.write_text(payload + "\n", encoding="utf-8")

        # Atomic rename within the same directory: the report is either the
        # previous version or the new one, never a truncated mix of both.
        os.replace(temporary, target)

        return target
    except OSError as error:
        raise GraphConstructionWriteError(
            f"Could not write the graph construction report into '{directory}': "
            f"{error}"
        ) from error


def load_graph_construction(path: Path) -> dict:
    """Read a graph construction report back from disk."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "GRAPH_CONSTRUCTION_DIRECTORY",
    "GRAPH_CONSTRUCTION_FILE_NAME",
    "load_graph_construction",
    "snapshot_directory",
    "write_graph_construction",
]
