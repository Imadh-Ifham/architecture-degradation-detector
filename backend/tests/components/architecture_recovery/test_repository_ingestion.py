import stat
from pathlib import Path

import pytest

from app.components.architecture_recovery.repository_ingestion.errors import (
    InvalidRepositorySource,
    RepositoryNotFound,
)
from app.components.architecture_recovery.repository_ingestion.service import (
    RepositoryIngestionService,
    build_repository_id,
)
from app.components.architecture_recovery.repository_ingestion.validation import (
    redact_credentials,
    validate_branch,
    validate_url,
)


class StubGitClient:
    """Records clone calls and materialises a fake working tree."""

    def __init__(self, commit: str = "0" * 40) -> None:
        self.commit = commit
        self.clones: list[tuple[str, str]] = []

    def clone(self, url: str, branch: str, destination: Path) -> None:
        self.clones.append((url, branch))
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "README.md").write_text("stub", encoding="utf-8")

    def head_commit(self, repository: Path) -> str:
        return self.commit


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/GoogleCloudPlatform/microservices-demo.git",
        "http://example.com/team/repo.git",
        "ssh://git@example.com/team/repo.git",
        "git://example.com/team/repo.git",
        "git@github.com:GoogleCloudPlatform/microservices-demo.git",
    ],
)
def test_validate_url_accepts_remote_sources(url: str) -> None:
    assert validate_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "not-a-url",
        "/local/path/to/repo",
        "file:///etc/passwd",
        "../relative/repo",
        "--upload-pack=touch /tmp/pwned",
        "https://",
    ],
)
def test_validate_url_rejects_everything_else(url: str) -> None:
    with pytest.raises(InvalidRepositorySource):
        validate_url(url)


@pytest.mark.parametrize(
    "branch",
    ["main", "develop", "feature/add-thing", "release-1.2.3"],
)
def test_validate_branch_accepts_valid_names(branch: str) -> None:
    assert validate_branch(branch) == branch


@pytest.mark.parametrize(
    "branch",
    [
        "",
        "   ",
        "-main",
        "--upload-pack=evil",
        "feature branch",
        "a..b",
        "x@{y}",
        "refs//x",
        "main/",
        "/main",
        "main.",
        "main.lock",
        "@",
        "a~1",
        "a^",
        "a:b",
        "a?b",
        "a*b",
        "a[b",
        "a\\b",
    ],
)
def test_validate_branch_rejects_invalid_names(branch: str) -> None:
    with pytest.raises(InvalidRepositorySource):
        validate_branch(branch)


def test_redact_credentials_hides_userinfo() -> None:
    redacted = redact_credentials("https://user:secret@example.com/repo.git")

    assert redacted == "https://***@example.com/repo.git"
    assert "secret" not in redacted


def test_build_repository_id_is_stable_and_filesystem_safe() -> None:
    url = "https://github.com/GoogleCloudPlatform/microservices-demo.git"

    first = build_repository_id(url, "main")

    assert first == build_repository_id(url, "main")
    assert first.startswith("microservices-demo-")
    assert first != build_repository_id(url, "develop")


def test_ingest_clones_and_records_metadata(tmp_path: Path) -> None:
    git = StubGitClient()
    service = RepositoryIngestionService(git_client=git, root=tmp_path)

    record = service.ingest(
        "https://github.com/GoogleCloudPlatform/microservices-demo.git",
        "main",
    )

    assert git.clones == [
        ("https://github.com/GoogleCloudPlatform/microservices-demo.git", "main")
    ]
    assert record.path.is_dir()
    assert (record.path / "README.md").is_file()
    assert record.commit == git.commit

    listed = service.list_ingested()

    assert [item.id for item in listed] == [record.id]
    assert listed[0].path.resolve() == record.path.resolve()


def test_reingesting_replaces_the_existing_clone(tmp_path: Path) -> None:
    git = StubGitClient()
    service = RepositoryIngestionService(git_client=git, root=tmp_path)
    url = "https://example.com/team/repo.git"

    first = service.ingest(url, "main")
    second = service.ingest(url, "main")

    assert first.id == second.id
    assert len(git.clones) == 2
    assert len(service.list_ingested()) == 1


def test_failed_clone_leaves_no_repository_behind(tmp_path: Path) -> None:
    class FailingGitClient(StubGitClient):
        def clone(self, url: str, branch: str, destination: Path) -> None:
            super().clone(url, branch, destination)
            raise RuntimeError("clone failed")

    service = RepositoryIngestionService(git_client=FailingGitClient(), root=tmp_path)

    with pytest.raises(RuntimeError):
        service.ingest("https://example.com/team/repo.git", "main")

    assert service.list_ingested() == []
    assert not _has_entries(tmp_path / ".staging")


def test_remove_deletes_the_workspace(tmp_path: Path) -> None:
    service = RepositoryIngestionService(git_client=StubGitClient(), root=tmp_path)
    record = service.ingest("https://example.com/team/repo.git", "main")

    service.remove(record.id)

    assert not record.path.exists()
    assert service.list_ingested() == []


def test_remove_clears_read_only_files(tmp_path: Path) -> None:
    """git marks packed objects read-only on Windows; removal must cope."""

    service = RepositoryIngestionService(git_client=StubGitClient(), root=tmp_path)
    record = service.ingest("https://example.com/team/repo.git", "main")

    locked = record.path / "packed-object.idx"
    locked.write_text("locked", encoding="utf-8")
    locked.chmod(stat.S_IREAD)

    service.remove(record.id)

    assert not record.path.exists()


@pytest.mark.parametrize(
    "repository_id",
    ["does-not-exist", "", "../escape", "..", "a/b", "Upper", "with space"],
)
def test_remove_rejects_unknown_or_unsafe_ids(
    tmp_path: Path, repository_id: str
) -> None:
    service = RepositoryIngestionService(git_client=StubGitClient(), root=tmp_path)

    with pytest.raises(RepositoryNotFound):
        service.remove(repository_id)


def _has_entries(directory: Path) -> bool:
    return directory.is_dir() and any(directory.iterdir())
