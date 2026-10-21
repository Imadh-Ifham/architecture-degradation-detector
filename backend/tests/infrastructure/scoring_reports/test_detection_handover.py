# Tests for the file adapter that reads degradation detection's hand-over: both files read
# unchanged, a run missing either file is None, ids that could leave the root refused.

import json
from pathlib import Path

import pytest

from app.infrastructure.scoring_reports import DetectionHandoverFiles


def write(root: Path, *, events: bool = True, package: bool = True) -> None:
    folder = root / "shop-0123456789ab" / "RUN-a"
    folder.mkdir(parents=True)
    if events:
        (folder / "events.json").write_text(json.dumps([{"event_id": "E1"}]), encoding="utf-8")
    if package:
        (folder / "release_package.json").write_text(json.dumps({"release_id": "v1"}), "utf-8")


def test_both_files_are_read_unchanged(tmp_path: Path) -> None:
    write(tmp_path)

    handover = DetectionHandoverFiles(tmp_path).read("shop-0123456789ab", "RUN-a")

    assert handover == {"events": [{"event_id": "E1"}], "package": {"release_id": "v1"}}


@pytest.mark.parametrize("missing", ["events", "package"])
def test_a_run_missing_a_file_is_none(tmp_path: Path, missing: str) -> None:
    write(tmp_path, **{missing: False})

    assert DetectionHandoverFiles(tmp_path).read("shop-0123456789ab", "RUN-a") is None


@pytest.mark.parametrize(
    ("system_id", "run_id"),
    [("..", "RUN-a"), ("shop-0123456789ab", "../RUN-a"), ("shop/x", "RUN-a"), ("", "RUN-a")],
)
def test_ids_that_could_leave_the_root_are_refused(
    tmp_path: Path, system_id: str, run_id: str
) -> None:
    write(tmp_path)

    assert DetectionHandoverFiles(tmp_path).read(system_id, run_id) is None
