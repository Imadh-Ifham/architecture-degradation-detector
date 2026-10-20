"""What one recovery run did, stage by stage.

Author: Imadh Ifham
Date: 2026-10-20
Description:
    The pipeline page can say that recovery ran; nothing could say how. The
    API composes the six stages in sequence and used to return only their
    summaries, so duration, order and the difference between "found nothing"
    and "did not run" were lost with the response.

    This records them. The composition root times each stage and writes one
    document beside the artifacts it produced, which is where everything else
    about the run already lives - so a release whose clone was removed loses
    its run record in the same way it loses its evidence, and the page says
    so rather than showing a stage list it cannot vouch for.

    **A record is written only by a run.** Nothing here infers a status from
    the presence of an artifact: a stage that was skipped has a record saying
    it was skipped and why, and a release analysed before this existed has no
    record at all, which the page reports as unavailable rather than as six
    successes.
"""

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .pipeline import RECOVERY_STAGES, RecoveryStage

RECOVERY_RUN_FILE = "recovery_run.json"

STATUS_COMPLETED = "completed"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"

SKIPPED_PREFIX = "skipped:"


@dataclass
class StageRecord:
    """One stage's execution record."""

    name: str
    order: int
    status: str
    duration_ms: int
    counts: dict[str, int] = field(default_factory=dict)
    note: str | None = None
    warnings: list[str] = field(default_factory=list)
    artifact: str | None = None
    artifact_present: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "order": self.order,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "counts": self.counts,
            "note": self.note,
            "warnings": self.warnings,
            "artifact": self.artifact,
            "artifact_present": self.artifact_present,
        }


class StageTimer:
    """Times one stage and turns what it returned into a record.

    The three outcomes are the three the pipeline can produce, and they are
    kept apart here because the whole point of the page is that a skipped
    stage must not read like a stage that found nothing: the composition root
    reports a skip as an error string prefixed `skipped:`, and this reads that
    prefix rather than guessing from a null summary.
    """

    def __init__(self, stage: RecoveryStage) -> None:
        self._stage = stage
        self._started = 0.0

    def __enter__(self) -> "StageTimer":
        self._started = time.perf_counter()
        return self

    def __exit__(self, *_: object) -> None:
        self.duration_ms = int((time.perf_counter() - self._started) * 1000)

    def record(
        self,
        *,
        summary: dict | None,
        error: str | None,
        report: object | None = None,
        artifact_directory: Path | None = None,
    ) -> StageRecord:
        """Build the record for this stage from what the handler returned."""

        status = (
            STATUS_COMPLETED
            if summary is not None and error is None
            else STATUS_SKIPPED
            if error and error.startswith(SKIPPED_PREFIX)
            else STATUS_FAILED
        )

        counts = {
            key: value
            for key, value in (summary or {}).items()
            if isinstance(value, int) and not isinstance(value, bool) and key != "path"
        }

        return StageRecord(
            name=self._stage.name,
            order=self._stage.order,
            status=status,
            duration_ms=self.duration_ms,
            counts=counts,
            note=_note(error),
            warnings=_warnings(report),
            artifact=self._stage.artifact,
            artifact_present=artifact_present(
                artifact_directory, self._stage.artifact
            ),
        )


def artifact_present(directory: Path | None, filename: str | None) -> bool:
    """Whether a stage's artifact is on disk.

    Searched a couple of directories deep rather than at a fixed path, because
    the stages do not agree on one: the inventory writes beside the clone and
    graph construction writes inside a directory named for the snapshot. A
    layout baked in here would be wrong the first time a stage chose another,
    and reporting a written artifact as missing is worse than the search.
    """

    if directory is None or not filename:
        return False

    for candidate in directory.rglob(filename):
        if len(candidate.relative_to(directory).parts) <= 3:
            return True

    return False


def build_run(
    *,
    repository: object,
    stages: list[StageRecord],
    started_at: datetime,
    finished_at: datetime,
) -> dict:
    """Assemble the document one run leaves behind."""

    return {
        "schema_version": "1.0.0",
        "repository_id": getattr(repository, "repository_key", None),
        "workspace_id": getattr(repository, "id", None),
        "release_id": getattr(repository, "release_id", None),
        "repository_url": getattr(repository, "url", None),
        "branch": getattr(repository, "branch", None),
        "commit_sha": getattr(repository, "commit", None),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_ms": int((finished_at - started_at).total_seconds() * 1000),
        "status": _run_status(stages),
        "stages": [stage.to_dict() for stage in stages],
        "stage_count": len(RECOVERY_STAGES),
    }


def write_run(directory: Path, document: dict) -> Path:
    """Write the record beside the artifacts, atomically.

    Atomic for the same reason the artifacts are: a reader must never see half
    a stage list, because a truncated one reads as a pipeline that stopped.
    """

    target = directory / RECOVERY_RUN_FILE
    payload = json.dumps(document, indent=2)

    handle, temporary = tempfile.mkstemp(
        dir=str(directory), prefix=f".{RECOVERY_RUN_FILE}.", suffix=".partial"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except OSError:
        Path(temporary).unlink(missing_ok=True)
        raise

    return target


def read_run(directory: Path | None) -> dict | None:
    """The record from a directory, or nothing when there is none to read."""

    if directory is None:
        return None

    path = directory / RECOVERY_RUN_FILE

    if not path.is_file():
        return None

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    return document if isinstance(document, dict) else None


def _run_status(stages: list[StageRecord]) -> str:
    """A run is only complete if every stage of the pipeline ran."""

    if any(stage.status == STATUS_FAILED for stage in stages):
        return STATUS_FAILED

    if any(stage.status == STATUS_SKIPPED for stage in stages):
        return "incomplete"

    return STATUS_COMPLETED


def _note(error: str | None) -> str | None:
    """Why a stage did not run, in the words the handler used."""

    if not error:
        return None

    if error.startswith(SKIPPED_PREFIX):
        return error[len(SKIPPED_PREFIX) :].strip()

    return error


def _warnings(report: object | None) -> list[str]:
    """Whatever the stage's own report called a warning."""

    found = getattr(report, "warnings", None)

    if not found:
        return []

    return [str(item) for item in found][:20]


def now() -> datetime:
    """A timestamp, in the timezone the rest of the run is recorded in."""

    return datetime.now(UTC)


__all__ = [
    "RECOVERY_RUN_FILE",
    "STATUS_COMPLETED",
    "STATUS_FAILED",
    "STATUS_SKIPPED",
    "StageRecord",
    "StageTimer",
    "build_run",
    "now",
    "read_run",
    "write_run",
]
