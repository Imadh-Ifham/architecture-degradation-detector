# Reads what degradation detection (C3) leaves for scoring after a run started from the app:
# <degradation_outputs_root>/<system>/<run_id>/events.json and release_package.json
# (app/api/degradation.py write_handover). Implements DetectionHandoverSource.

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.infrastructure.scoring_reports.file_store import RUN_ID

EVENTS_FILE = "events.json"
PACKAGE_FILE = "release_package.json"


class DetectionHandoverFiles:
    def __init__(self, root: Path) -> None:
        self._root = root

    def read(self, system_id: str, detection_run_id: str) -> Mapping[str, Any] | None:
        # both ids must be plain folder names, so a request can never leave the root
        if not (RUN_ID.fullmatch(system_id) and RUN_ID.fullmatch(detection_run_id)):
            return None
        folder = self._root / system_id / detection_run_id
        events, package = folder / EVENTS_FILE, folder / PACKAGE_FILE
        if not (events.is_file() and package.is_file()):
            return None
        return {
            "events": json.loads(events.read_text(encoding="utf-8")),
            "package": json.loads(package.read_text(encoding="utf-8")),
        }
