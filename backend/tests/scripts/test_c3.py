"""`c3 schemas export`: JSON Schemas are generated from the Pydantic models, never hand-edited."""

import json
from pathlib import Path

from typer.testing import CliRunner

from app.components.degradation_detection.config import C3Config
from scripts.c3 import SCHEMA_DIR, app, render_schemas

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
