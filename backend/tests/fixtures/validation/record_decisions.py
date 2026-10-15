"""Record the decision history the two releases produce.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    Scans both releases of the subject working tree, in order, and writes the
    resulting event log to `decisions/<repository>.jsonl`.

    Why it is recorded rather than written by hand. The corpus is the scan's
    own output, so a hand-written copy would be a second description of input
    that already exists - and the two would drift, which is exactly the
    failure the fixture is supposed to catch. Recording it instead means a
    change to a parser arrives as a reviewable diff in this file.

    The order matters and is the point. The earlier release is scanned first,
    so the later one can be compared against what the log already holds; that
    comparison is where the supersession comes from, and it cannot happen in
    a single scan of a single release.

    Run it deliberately, never from a request:

        uv run python tests/fixtures/validation/record_decisions.py

    The output is committed.
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[2]

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.components.architecture_validation.decision_knowledge import (  # noqa: E402
    DecisionKnowledgeService,
    SourceRequest,
)
from app.infrastructure.decision_log import JsonlDecisionStore  # noqa: E402

REPOSITORY_ID = "online-boutique"
RELEASES = ("v0.9.0", "v0.10.0")
MODE = "combined"
SUBJECT = HERE / "subject"
SNAPSHOTS = BACKEND / "data" / "snapshots"
TARGET = HERE / "decisions"

RECORDED_AT = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
"""Fixed, so re-recording an unchanged scan produces an unchanged file.

The timestamp is injected into the scan rather than read from the clock for
the same reason: a corpus that differs on every run cannot be a fixture.
"""


class SubjectWorkspace:
    """Reads the generated subject tree in place of an ingested checkout."""

    def read_text(self, repository_id: str, release_id: str, path: str) -> str:
        return (SUBJECT / release_id / path).read_text(encoding="utf-8")

    def list_paths(self, repository_id: str, release_id: str, pattern: str) -> list[str]:
        root = SUBJECT / release_id
        return sorted(
            str(match.relative_to(root)).replace("\\", "/")
            for match in root.glob(pattern)
            if match.is_file()
        )


def manifest_paths(release_id: str) -> tuple[str, ...]:
    """The manifests recovery located, read from the recorded snapshot."""

    document = json.loads(
        (SNAPSHOTS / f"snapshot_{release_id}.json").read_text(encoding="utf-8")
    )
    return tuple(document["manifest_paths"])


def record_all() -> Path:
    """Scan every release in order and write the log."""

    sys.path.insert(0, str(HERE))
    import build_subject_tree

    build_subject_tree.build_all()

    TARGET.mkdir(parents=True, exist_ok=True)
    log = TARGET / f"{REPOSITORY_ID}.jsonl"
    log.unlink(missing_ok=True)

    service = DecisionKnowledgeService(SubjectWorkspace(), JsonlDecisionStore(TARGET))

    for release_id in RELEASES:
        request = SourceRequest(
            code_repository_id=REPOSITORY_ID,
            release_id=release_id,
            extracted_at=RECORDED_AT,
            manifest_paths=manifest_paths(release_id),
        )
        outcome = service.append_scan(request, service.collect(request, MODE))
        print(
            f"  {release_id}: {outcome.recorded} recorded, "
            f"{outcome.closed} closed, {outcome.unchanged} unchanged"
        )

    print(f"  {log.name}: {len(log.read_text(encoding='utf-8').splitlines())} events")
    return log


if __name__ == "__main__":
    record_all()
