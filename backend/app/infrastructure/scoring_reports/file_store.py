# Reads C4's saved runs from <scoring_outputs_root>/<system>/<run_id>/ (CLAUDE.md §6), as plain
# documents (infrastructure may not import components). Implements SavedReportSource.

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

MANIFEST_FILE = "c4_run_manifest.json"
REPORT_FILE = "c4_report.json"
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ScoringReportFileStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def runs(self) -> Sequence[Mapping[str, object]]:
        # every readable manifest; unreadable ones are logged and left out
        if not self._root.is_dir():
            return []
        documents = []
        for path in sorted(self._root.glob(f"*/*/{MANIFEST_FILE}")):
            document = self._read(path)
            if document is not None:
                documents.append(document)
        return documents

    def reports(self, run_id: str) -> Sequence[Mapping[str, object]]:
        # run_id must be a plain folder name, so a request can never leave the root
        if not RUN_ID.fullmatch(run_id) or not self._root.is_dir():
            return []
        documents = []
        for system in sorted(p for p in self._root.iterdir() if p.is_dir()):
            path = system / run_id / REPORT_FILE
            if path.is_file():
                document = self._read(path)
                if document is not None:
                    documents.append(document)
        return documents

    def files(self, run_id: str, name: str) -> Sequence[bytes]:
        # one file of every run folder with that id, as bytes; plain names only
        if not (RUN_ID.fullmatch(run_id) and RUN_ID.fullmatch(name)) or not self._root.is_dir():
            return []
        found = []
        for system in sorted(p for p in self._root.iterdir() if p.is_dir()):
            path = system / run_id / name
            if path.is_file():
                found.append(path.read_bytes())
        return found

    @staticmethod
    def _read(path: Path) -> Mapping[str, object] | None:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            log.warning("saved_report_unreadable", path=path.as_posix(), error=str(error))
            return None
        if not isinstance(document, dict):
            log.warning("saved_report_unreadable", path=path.as_posix(), error="not an object")
            return None
        return document
