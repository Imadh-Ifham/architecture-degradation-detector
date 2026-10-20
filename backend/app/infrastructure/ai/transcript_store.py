"""A run's model calls, on disk.

Author: Aman Mohamed M.A
Date: 2026-10-21
Description:
    Keeps what a run sent to each model and what came back, beside the graph
    that run published.

    On disk rather than in memory for the same reason the graph is: the
    published document outlives the session that produced it, and a screen
    opened after a refresh would otherwise show a result with no way left to
    check what produced it. Keeping the two artifacts in step matters more
    than it sounds - a transcript that vanished on restart would be absent
    exactly when somebody came back to ask a question about yesterday's run.

    The same atomic write as the graph store, for the same reason: a reader
    gets one whole transcript or the previous one, never a truncated file that
    parses as a run that called nothing.
"""

import json
import os
import tempfile
from pathlib import Path

LATEST_FILENAME = "latest.transcript.json"


class ModelTranscriptFileStore:
    """Writes a run's transcript under `<root>/<repository_id>/<release_id>/`."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def write(self, document: dict) -> str:
        """Store one run's transcript and return the path it landed at.

        The document names its own run, repository and release, so nothing is
        passed twice and the file cannot be filed under a release it does not
        describe.
        """

        directory = self._directory(document["repository_id"], document["release_id"])
        directory.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(document, indent=2, sort_keys=False)
        target = directory / f"{document['run_id']}.transcript.json"
        _write_atomically(target, payload)
        _write_atomically(directory / LATEST_FILENAME, payload)

        return str(target)

    def read(self, repository_id: str, release_id: str) -> dict | None:
        """The most recent transcript for one release, if one was kept.

        `None` rather than an exception, and rather than an empty transcript.
        A release validated before this was written has a graph and no
        transcript, and that is a different statement from a run that called
        no model - which is itself a finding.
        """

        latest = self._directory(repository_id, release_id) / LATEST_FILENAME
        if not latest.is_file():
            return None
        return json.loads(latest.read_text(encoding="utf-8"))

    def _directory(self, repository_id: str, release_id: str) -> Path:
        return self._root / repository_id / release_id


def _write_atomically(target: Path, payload: str) -> None:
    """Write `payload` to `target` so a reader never sees it half-written."""

    handle, temporary = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".partial"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


__all__ = ["LATEST_FILENAME", "ModelTranscriptFileStore"]
