"""`c3 schemas export`: JSON Schemas are generated from the Pydantic models, never hand-edited."""

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.components.degradation_detection.config import C3Config
from app.components.degradation_detection.stub import StubService
from scripts import c3
from scripts.c3 import SCHEMA_DIR, app, render_schemas
from tests.components.degradation_detection.fakes import (
    InMemoryAnalysisRunRepository,
    InMemoryReleaseRepository,
)

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


# --- c3 detect --------------------------------------------------------------------------------


def detect_rows(output: str) -> list[list[str]]:
    """The instance table: release, gate, anti_pattern_type, members (comma-joined)."""
    return [line.split() for line in output.splitlines() if line.startswith("v")]


def test_detect_instance_table_matches_the_manifest(
    memory_repo: InMemoryReleaseRepository, stub_dir: Path
) -> None:
    CliRunner().invoke(app, ["ingest", str(stub_dir)])

    result = CliRunner().invoke(app, ["detect", "--system", "shopfront"])

    assert result.exit_code == 0, result.output
    rows = detect_rows(result.output)
    truth = StubService().generate().ground_truth
    assert sorted({row[0] for row in rows}) == [r.release_id for r in truth.releases]
    for planted in truth.instances:  # S1 CyclicDependency, S9 SharedPersistence
        found = {
            row[0]: tuple(row[3].split(",")) for row in rows if row[2] == planted.anti_pattern_type
        }
        assert found == planted.members_by_release, planted.scenario


def test_detect_shows_the_gate_status(
    memory_repo: InMemoryReleaseRepository, stub_dir: Path
) -> None:
    CliRunner().invoke(app, ["ingest", str(stub_dir)])

    result = CliRunner().invoke(app, ["detect", "--system", "shopfront"])

    assert {row[1] for row in detect_rows(result.output) if row[0] == "v1.5.0"} == {"DOWNWEIGHTED"}


def test_detect_unknown_system_fails(memory_repo: InMemoryReleaseRepository) -> None:
    result = CliRunner().invoke(app, ["detect", "--system", "nowhere"])

    assert result.exit_code == 1
    assert "no releases" in result.output


# --- c3 align ---------------------------------------------------------------------------------


def test_align_prints_lineages_tracks_and_writes_the_alignment_sample(
    memory_repo: InMemoryReleaseRepository, stub_dir: Path, tmp_path: Path
) -> None:
    CliRunner().invoke(app, ["ingest", str(stub_dir)])
    out = tmp_path / "shopfront" / "alignment_sample.csv"

    result = CliRunner().invoke(app, ["align", "--system", "shopfront", "--out", str(out)])

    assert result.exit_code == 0, result.output
    rename = next(line for line in result.output.splitlines() if "RENAME" in line)
    assert rename.split() == [
        "v1.4.0",
        "RENAME",
        "ALIAS",
        "LIN-order-svc@v1.0.0",
        "order-svc",
        "order-service",
    ]
    tracks = {line.split()[0]: line.split()[1:] for line in result.output.splitlines()}
    assert tracks["AP-CyclicDependency:inventory@v1.1.0"] == [  # S1, one track through S4
        "v1.1.0",
        "v1.9.0",
        "OPEN",
        "persistent",
        "3>3>3>4>4>4>5>5>5",
    ]
    assert tracks["AP-SharedPersistence:orders_db@v1.2.0"][-1] == "2>2>3>3>4>4>5>5"  # S9
    assert "10 releases, 15 lineages, 1 renames, 1 decisions, 14 instance tracks" in result.output
    lines = out.read_bytes().decode("utf-8").split("\n")
    assert len([line for line in lines if line]) == 2  # header + the S4 alias link
    assert lines[1].startswith("v1.3.0,v1.4.0,order-svc,order-service,service,ALIAS,LINKED")


def test_align_unknown_system_fails(memory_repo: InMemoryReleaseRepository) -> None:
    result = CliRunner().invoke(app, ["align", "--system", "nowhere"])

    assert result.exit_code == 1
    assert "no releases" in result.output


# --- c3 series --------------------------------------------------------------------------------


def test_series_writes_the_series_table(
    memory_repo: InMemoryReleaseRepository, stub_dir: Path, tmp_path: Path
) -> None:
    CliRunner().invoke(app, ["ingest", str(stub_dir)])
    out = tmp_path / "shopfront" / "series.csv"

    result = CliRunner().invoke(app, ["series", "--system", "shopfront", "--out", str(out)])

    assert result.exit_code == 0, result.output
    rows = out.read_bytes().decode("utf-8").split("\n")
    assert rows[0] == "scope,subject_id,metric,ordinal,release_id,value"
    s1 = [
        r
        for r in rows
        if r.startswith("INSTANCE,AP-CyclicDependency:inventory@v1.1.0,member_count")
    ]
    assert [r.rsplit(",", 1)[1] for r in s1] == ["3", "3", "3", "4", "4", "4", "5", "5", "5"]
    assert "series: " in result.output and f"wrote {out}" in result.output


def test_series_unknown_system_fails(memory_repo: InMemoryReleaseRepository) -> None:
    result = CliRunner().invoke(app, ["series", "--system", "nowhere"])

    assert result.exit_code == 1
    assert "no releases" in result.output


def test_trends_prints_the_worsening_trends_and_candidates_and_writes_the_events(
    memory_repo: InMemoryReleaseRepository, stub_dir: Path, tmp_path: Path
) -> None:
    CliRunner().invoke(app, ["ingest", str(stub_dir)])
    out = tmp_path / "events.json"

    result = CliRunner().invoke(
        app, ["trends", "--system", "shopfront", "--run-id", "RUN-cli", "--out", str(out)]
    )

    assert result.exit_code == 0, result.output
    events = json.loads(out.read_bytes().decode("utf-8"))
    assert events, "the stub has planted worsening trends"
    assert {e["run_id"] for e in events} == {"RUN-cli"}
    assert any(
        e["scope"] == "INSTANCE" and e["anti_pattern_type"] == "CyclicDependency" for e in events
    )
    assert "series tested" in result.output
    assert "AP-CyclicDependency:inventory@v1.1.0" in result.output
    assert f"{len(events)} events (run RUN-cli); wrote {out}" in result.output


def test_trends_default_run_id_is_new_and_names_the_output_folder(
    memory_repo: InMemoryReleaseRepository,
    stub_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    CliRunner().invoke(app, ["ingest", str(stub_dir)])
    monkeypatch.setattr(c3, "OUT_DIR", tmp_path)

    result = CliRunner().invoke(app, ["trends", "--system", "shopfront"])

    assert result.exit_code == 0, result.output
    [written] = list(tmp_path.glob("RUN-*/events.json"))
    run_id = written.parent.name
    assert {e["run_id"] for e in json.loads(written.read_text(encoding="utf-8"))} == {run_id}


def test_trends_unknown_system_fails(memory_repo: InMemoryReleaseRepository) -> None:
    result = CliRunner().invoke(app, ["trends", "--system", "nowhere"])

    assert result.exit_code == 1
    assert "no releases" in result.output


# --- c3 run / report / baseline (T-13) ---------------------------------------------------------


@pytest.fixture
def memory_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> InMemoryAnalysisRunRepository:
    """In-memory run store, a fixed code version, and out/ under the test's tmp dir."""
    runs = InMemoryAnalysisRunRepository()
    monkeypatch.setattr(c3, "run_repository", lambda: runs)
    monkeypatch.setattr(c3, "code_version", lambda: "test-sha")
    monkeypatch.setattr(c3, "OUT_DIR", tmp_path / "out")
    return runs


def test_run_ingests_analyses_and_writes_every_output(
    memory_repo: InMemoryReleaseRepository,
    memory_runs: InMemoryAnalysisRunRepository,
    stub_dir: Path,
    tmp_path: Path,
) -> None:
    """Plan T-13 acceptance: one command, from an empty store, reproduces everything."""
    result = CliRunner().invoke(app, ["run", "--system", "shopfront", "--ingest", str(stub_dir)])

    assert result.exit_code == 0, result.output
    [run] = memory_runs.runs.values()
    assert run.status.value == "COMPLETED" and run.code_version == "test-sha"
    out = tmp_path / "out" / run.run_id
    events = json.loads((out / "events.json").read_text(encoding="utf-8"))
    assert events and {e["run_id"] for e in events} == {run.run_id}
    assert (out / "series.csv").exists()
    assert (
        (out / "report.md")
        .read_text(encoding="utf-8")
        .startswith(f"# C3 analysis run {run.run_id}")
    )
    assert {p.name for p in (out / "plots").glob("*.png")} == {
        f"{e['event_id']}.png" for e in events
    }
    assert "10 stored" in result.output  # the ingest summary
    assert f"run {run.run_id} COMPLETED" in result.output
    assert f"{len(events)} events" in result.output
    assert f"wrote {len(events) + 3} files to {out}" in result.output


def test_run_without_ingest_reads_the_store(
    memory_repo: InMemoryReleaseRepository,
    memory_runs: InMemoryAnalysisRunRepository,
    stub_dir: Path,
) -> None:
    CliRunner().invoke(app, ["ingest", str(stub_dir)])

    result = CliRunner().invoke(app, ["run", "--system", "shopfront"])

    assert result.exit_code == 0, result.output
    assert "stored" not in result.output  # nothing ingested by this command
    assert len(memory_runs.runs) == 1


def test_run_unknown_system_fails(
    memory_repo: InMemoryReleaseRepository, memory_runs: InMemoryAnalysisRunRepository
) -> None:
    result = CliRunner().invoke(app, ["run", "--system", "nowhere"])

    assert result.exit_code == 1
    assert "no releases" in result.output
    assert memory_runs.runs == {}


def test_report_re_renders_a_stored_run(
    memory_repo: InMemoryReleaseRepository,
    memory_runs: InMemoryAnalysisRunRepository,
    stub_dir: Path,
    tmp_path: Path,
) -> None:
    CliRunner().invoke(app, ["run", "--system", "shopfront", "--ingest", str(stub_dir)])
    [run_id] = memory_runs.runs
    report = tmp_path / "out" / run_id / "report.md"
    first = report.read_bytes()
    report.unlink()

    result = CliRunner().invoke(app, ["report", "--run-id", run_id])

    assert result.exit_code == 0, result.output
    assert report.read_bytes() == first


def test_report_unknown_run_fails(
    memory_repo: InMemoryReleaseRepository, memory_runs: InMemoryAnalysisRunRepository
) -> None:
    result = CliRunner().invoke(app, ["report", "--run-id", "RUN-missing"])

    assert result.exit_code == 1
    assert "RUN-missing" in result.output


def test_baseline_prints_the_static_flags_at_the_last_release(
    memory_repo: InMemoryReleaseRepository, stub_dir: Path
) -> None:
    CliRunner().invoke(app, ["ingest", str(stub_dir)])

    result = CliRunner().invoke(app, ["baseline", "--system", "shopfront"])

    assert result.exit_code == 0, result.output
    assert any(
        line.split()[:3] == ["v1.9.0", "legacy-auth", "fan_in"]
        for line in result.output.splitlines()
    )


def test_code_version_names_the_commit() -> None:
    assert re.fullmatch(r"[0-9a-f]{7,40}(-dirty)?|unknown", c3.code_version())
