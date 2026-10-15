import subprocess
from pathlib import Path

import pytest

from app.infrastructure.git.client import GitClient, GitCommandError


def _run_git(*arguments: str, cwd: Path) -> None:
    subprocess.run(
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


def _rev_parse(repository: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )

    return completed.stdout.strip()


@pytest.fixture
def origin_repository(tmp_path: Path) -> Path:
    origin = tmp_path / "origin"
    origin.mkdir()

    _run_git("init", "-b", "main", cwd=origin)
    (origin / "README.md").write_text("hello", encoding="utf-8")
    _run_git("add", ".", cwd=origin)
    _run_git("commit", "-m", "Initial commit", cwd=origin)

    return origin


def test_clone_checks_out_the_requested_branch(
    tmp_path: Path, origin_repository: Path
) -> None:
    client = GitClient(timeout_seconds=60)
    destination = tmp_path / "clone"

    client.clone(str(origin_repository), "main", destination)

    assert (destination / "README.md").read_text(encoding="utf-8") == "hello"


def test_head_commit_matches_the_origin(tmp_path: Path, origin_repository: Path) -> None:
    client = GitClient(timeout_seconds=60)
    destination = tmp_path / "clone"

    client.clone(str(origin_repository), "main", destination)

    head = client.head_commit(destination)

    assert head == _rev_parse(origin_repository)


def test_clone_of_unknown_branch_raises(
    tmp_path: Path, origin_repository: Path
) -> None:
    client = GitClient(timeout_seconds=60)

    with pytest.raises(GitCommandError):
        client.clone(str(origin_repository), "does-not-exist", tmp_path / "clone")
