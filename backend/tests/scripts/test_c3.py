"""`c3 schemas export`: JSON Schemas are generated from the Pydantic models, never hand-edited."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.components.degradation_detection.config import C3Config
from scripts import c3
from scripts.c3 import SCHEMA_DIR, app, render_schemas
from tests.components.degradation_detection.fakes import InMemoryReleaseRepository

EXPECTED_FILES = {"c3_input.schema.json", "c3_output.schema.json", "c3_audit.schema.json"}


def test_all_three_contracts_are_exported() -> None:
    assert set(render_schemas()) == EXPECTED_FILES


def test_committed_schemas_match_the_models() -> None:
    """Snapshot: fails when a model changes without re-export, or a schema file is hand-edited.

    Fix with `uv run python -m scripts.c3 schemas export` and review the diff.
    """
    for name, rendered in render_schemas().items():
        path = SCHEMA_DIR / name
        assert path.exists(), f"{name} has not been exported"
        assert path.read_text(encoding="utf-8") == rendered, f"{name} is stale"

    assert {p.name for p in SCHEMA_DIR.glob("*.json")} == EXPECTED_FILES


def test_export_command_is_deterministic(tmp_path: Path) -> None:
    runner = CliRunner()

    first = runner.invoke(app, ["schemas", "export", "--out", str(tmp_path)])
    written = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    second = runner.invoke(app, ["schemas", "export", "--out", str(tmp_path)])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert set(written) == EXPECTED_FILES
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == written
    assert b"\r\n" not in written["c3_output.schema.json"]


def test_config_show_prints_the_config_and_its_hash() -> None:
    result = CliRunner().invoke(app, ["config", "show"])

    assert result.exit_code == 0, result.output
    shown = json.loads(result.stdout)
    assert shown["config_hash"] == C3Config().config_hash
    assert shown["config"]["trend"]["alpha"] == 0.05


def test_config_show_reads_the_given_file(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("trend:\n  alpha: 0.01\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["config", "show", "--config", str(path)])

    assert result.exit_code == 0, result.output
    shown = json.loads(result.stdout)
    assert shown["config"]["trend"]["alpha"] == 0.01
    assert shown["config_hash"] != C3Config().config_hash


def test_config_show_rejects_a_typo(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("trend:\n  alhpa: 0.01\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["config", "show", "--config", str(path)])

    assert result.exit_code == 2
    assert "alhpa" in result.stderr
    assert result.stdout == ""


def test_log_level_option_is_checked() -> None:
    result = CliRunner().invoke(app, ["--log-level", "LOUD", "config", "show"])

    assert result.exit_code == 2


def test_stub_generate_writes_the_system_and_is_repeatable(tmp_path: Path) -> None:
    runner = CliRunner()

    first = runner.invoke(app, ["stub", "generate", "--out", str(tmp_path), "--seed", "7"])
    written = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    second = runner.invoke(app, ["stub", "generate", "--out", str(tmp_path), "--seed", "7"])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert len(written) == 12
    assert "ground_truth.yaml" in written
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == written
    assert all(b"\r\n" not in content for content in written.values())


def test_stub_series_writes_the_series_fixtures(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["stub", "series", "--out", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "rising_exact.json").exists()
    assert len(list(tmp_path.iterdir())) == 11


# --- c3 ingest --------------------------------------------------------------------------------


@pytest.fixture
def memory_repo(monkeypatch: pytest.MonkeyPatch) -> InMemoryReleaseRepository:
    """Replace the PostgreSQL repository with the in-memory fake for one test."""
    repo = InMemoryReleaseRepository()
    monkeypatch.setattr(c3, "release_repository", lambda: repo)
    return repo


@pytest.fixture
def stub_dir(tmp_path: Path) -> Path:
    out = tmp_path / "shopfront"
    result = CliRunner().invoke(app, ["stub", "generate", "--out", str(out)])
    assert result.exit_code == 0, result.output
    return out


def test_ingest_directory_prints_a_summary(
    memory_repo: InMemoryReleaseRepository, stub_dir: Path
) -> None:
    result = CliRunner().invoke(app, ["ingest", str(stub_dir)])

    assert result.exit_code == 0, result.output
    assert "REJECTED  shopfront__v1.3.1-hotfix.json  DANGLING_DEPENDENCY" in result.stdout
    assert "STORED    shopfront__v1.5.0.json  shopfront v1.5.0 DOWNWEIGHTED" in result.stdout
    assert result.stdout.splitlines()[-1] == (
        "11 packages: 10 stored, 0 unchanged, 1 rejected "
        "(gate: 9 accepted, 1 downweighted, 0 excluded)"
    )
    assert len(memory_repo.releases) == 10


def test_ingest_re_run_is_a_no_op(memory_repo: InMemoryReleaseRepository, stub_dir: Path) -> None:
    CliRunner().invoke(app, ["ingest", str(stub_dir)])

    result = CliRunner().invoke(app, ["ingest", str(stub_dir)])

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[-1].startswith(
        "11 packages: 0 stored, 10 unchanged, 1 rejected"
    )


def test_ingest_single_file(memory_repo: InMemoryReleaseRepository, stub_dir: Path) -> None:
    result = CliRunner().invoke(app, ["ingest", str(stub_dir / "shopfront__v1.0.0.json")])

    assert result.exit_code == 0, result.output
    assert list(memory_repo.releases) == [("shopfront", "v1.0.0")]


def test_ingest_reads_at_most_one_byte_over_the_cap(
    memory_repo: InMemoryReleaseRepository, stub_dir: Path, tmp_path: Path
) -> None:
    config = tmp_path / "small.yaml"
    config.write_text("ingest: {max_package_bytes: 100}\n", encoding="utf-8")

    result = CliRunner().invoke(
        app, ["ingest", str(stub_dir / "shopfront__v1.0.0.json"), "--config", str(config)]
    )

    assert result.exit_code == 0, result.output
    assert "PACKAGE_TOO_LARGE" in result.stdout
    assert memory_repo.releases == {}


def test_ingest_missing_path_fails(memory_repo: InMemoryReleaseRepository, tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["ingest", str(tmp_path / "nowhere")])

    assert result.exit_code == 2
    assert memory_repo.releases == {}
