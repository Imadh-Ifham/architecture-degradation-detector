# Tests for C4's PyDriller history source on a tiny git repo with fixed dates (C4-T12).

from pathlib import Path
from typing import Any

import pytest

from app.infrastructure.git.history import PyDrillerHistorySource
from tests.components.degradation_scoring.support import ORDER, build_tiny_repo


@pytest.fixture(scope="module")
def tiny(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, str]]:
    root = tmp_path_factory.mktemp("tiny-repo")
    return root, build_tiny_repo(root)


def rows(root: Path, from_tag: str = "v1.0.0", to_tag: str = "v1.1.0") -> list[dict[str, object]]:
    return PyDrillerHistorySource().commits(str(root), from_tag, to_tag)


def files(row: dict[str, object]) -> list[Any]:
    value = row["files"]
    assert isinstance(value, list)
    return value


def test_range_excludes_the_start_tag_merges_and_later_commits(
    tiny: tuple[Path, dict[str, str]],
) -> None:
    root, hashes = tiny

    assert [row["hash"] for row in rows(root)] == [
        hashes[label] for label in ("c2", "c1", "c3", "c4", "c5")
    ]


def test_row_fields(tiny: tuple[Path, dict[str, str]]) -> None:
    root, _ = tiny
    c1 = rows(root)[1]

    assert c1["author_email"] == "Alice@Example.com"  # as recorded; lower-cased in T13
    assert c1["committed_at"] == "2026-01-05T12:00:00+00:00"
    assert c1["message"] == "order: rework totals"
    assert {"path": ORDER, "added": 4, "deleted": 1} in files(c1)


def test_paths_are_posix_and_unfiltered(tiny: tuple[Path, dict[str, str]]) -> None:
    root, _ = tiny
    paths = {f["path"] for f in files(rows(root)[1])}

    assert paths == {ORDER, "vendor/lib/Dep.java", "target/Out.java", "src/cartservice/bin/Cart.cs"}


def test_deleted_file_keeps_its_old_path(tiny: tuple[Path, dict[str, str]]) -> None:
    root, _ = tiny
    docs = rows(root)[3]

    assert {"path": "vendor/lib/Dep.java", "added": 0, "deleted": 3} in files(docs)


def test_single_commit_range(tiny: tuple[Path, dict[str, str]]) -> None:
    root, hashes = tiny

    only = rows(root, hashes["c3"], hashes["c4"])

    assert [row["hash"] for row in only] == [hashes["c4"]]
    assert rows(root, "v1.1.0", "v1.1.0") == []
