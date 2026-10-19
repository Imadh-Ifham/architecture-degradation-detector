"""Revision selection in the git adapter.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Proves that one explicit revision can be checked out, and that the three
    dates an analysis reports are read from the places they claim to come from:
    a tag's own date, the commit's author date, and nothing invented when a
    lightweight tag carries no date.

    Local repositories only; no network access.
"""

import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from app.infrastructure.git.client import GitClient


def _git(*arguments: str, cwd: Path) -> str:
    completed = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            *arguments,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )

    return completed.stdout.strip()


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    """A repository with two commits, one annotated and one lightweight tag."""

    repository = tmp_path / "origin"
    repository.mkdir()

    _git("init", "-b", "main", cwd=repository)
    (repository / "README.md").write_text("first", encoding="utf-8")
    _git("add", ".", cwd=repository)
    _git("commit", "-m", "First", cwd=repository)
    _git("tag", "-a", "v1.0.0", "-m", "Release 1.0.0", cwd=repository)

    (repository / "README.md").write_text("second", encoding="utf-8")
    _git("add", ".", cwd=repository)
    _git("commit", "-m", "Second", cwd=repository)
    _git("tag", "v2.0.0", cwd=repository)

    return repository


def clause(repository: Path, revision: str) -> str:
    """Return the full SHA a revision resolves to."""

    return _git("rev-parse", f"{revision}^{{commit}}", cwd=repository)


def test_clone_at_a_tag_checks_out_the_tagged_tree(
    tmp_path: Path, origin: Path
) -> None:
    client = GitClient(timeout_seconds=60)
    destination = tmp_path / "tagged"

    client.clone_at(str(origin), "v1.0.0", destination)

    assert (destination / "README.md").read_text(encoding="utf-8") == "first"
    assert client.head_commit(destination) == clause(origin, "v1.0.0")


def test_clone_at_a_commit_sha_checks_out_that_commit(
    tmp_path: Path, origin: Path
) -> None:
    client = GitClient(timeout_seconds=60)
    destination = tmp_path / "sha"
    sha = clause(origin, "v1.0.0")

    client.clone_at(str(origin), sha, destination)

    assert (destination / "README.md").read_text(encoding="utf-8") == "first"
    assert client.head_commit(destination) == sha


def test_is_tag_distinguishes_a_tag_from_a_commit(tmp_path: Path, origin: Path) -> None:
    client = GitClient(timeout_seconds=60)
    destination = tmp_path / "clone"

    client.clone(str(origin), "main", destination)

    assert client.is_tag(destination, "v1.0.0") is True
    assert client.is_tag(destination, "v2.0.0") is True
    assert client.is_tag(destination, clause(origin, "v1.0.0")) is False
    assert client.is_tag(destination, "main") is False


def test_annotated_tag_has_its_own_date(tmp_path: Path, origin: Path) -> None:
    client = GitClient(timeout_seconds=60)
    destination = tmp_path / "clone"

    client.clone(str(origin), "main", destination)
    tagged = client.tag_date(destination, "v1.0.0")

    assert isinstance(tagged, datetime)
    assert tagged.tzinfo is not None


def test_lightweight_tag_has_no_date_of_its_own(
    tmp_path: Path, origin: Path
) -> None:
    """The date is absent rather than borrowed from the commit.

    A lightweight tag is just a name; reporting the author date as a release
    date would present "when the work was written" as "when it was published".
    """

    client = GitClient(timeout_seconds=60)
    destination = tmp_path / "clone"

    client.clone(str(origin), "main", destination)

    assert client.tag_date(destination, "v2.0.0") is None


def test_commit_date_is_an_aware_author_date(tmp_path: Path, origin: Path) -> None:
    client = GitClient(timeout_seconds=60)
    destination = tmp_path / "clone"

    client.clone(str(origin), "main", destination)
    date = client.commit_date(destination, "HEAD")

    assert isinstance(date, datetime)
    assert date.tzinfo is not None
