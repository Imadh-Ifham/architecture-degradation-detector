# Tests for scripts/c4_rank.py (C4-T20): the fixture run writes every output file plus the log,
# the switches reach the run, and the script ranks exactly like the service.

import json
from pathlib import Path
from typing import Any

import pytest

from app.components.degradation_scoring import DegradationScoringService
from app.domain.severity_report import DataProvenance
from app.infrastructure.git.history import PyDrillerHistorySource
from scripts import c4_rank
from tests.components.degradation_scoring.support import (
    FIXTURES,
    adr_index_document,
    default_config,
    load_fixture,
)

EVENTS = FIXTURES / "events" / "fixture_events.v1.json"
GRAPH = FIXTURES / "graphs" / "fixture_release_package.v1.5.0.json"


def run_script(tmp_path: Path, *extra: str, run_id: str = "script-run") -> dict[str, Any]:
    code = c4_rank.main(
        [
            "--events",
            str(EVENTS),
            "--graph",
            str(GRAPH),
            "--run-id",
            run_id,
            "--outputs-root",
            str(tmp_path),
            *extra,
        ]
    )
    assert code == 0
    directory = tmp_path / "c4-fixture-shop" / run_id
    manifest: dict[str, Any] = json.loads(
        (directory / "c4_run_manifest.json").read_text(encoding="utf-8")
    )
    return manifest


def test_fixture_run_writes_every_output_and_the_log(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_script(tmp_path, "--adr-index", str(FIXTURES / "adr"))
    directory = tmp_path / "c4-fixture-shop" / "script-run"
    printed = json.loads(capsys.readouterr().out)

    assert sorted(p.relative_to(directory).as_posix() for p in directory.rglob("*.*")) == [
        "c4_quarantine.json",
        "c4_report.html",
        "c4_report.json",
        "c4_run_manifest.json",
        "logs/c4.jsonl",
    ]
    log_lines = (directory / "logs" / "c4.jsonl").read_text(encoding="utf-8").splitlines()
    assert any(json.loads(line).get("reason") == "unresolved_element" for line in log_lines)
    assert not list(tmp_path.glob(".*.jsonl"))
    assert printed["ranked"] == 9
    assert printed["active_dimensions"] == ["blast_radius", "adr_violation", "persistence"]


def test_switches_reach_the_run(tmp_path: Path) -> None:
    manifest = run_script(
        tmp_path, "--adr-index", str(FIXTURES / "adr"), "--no-adr", "--topsis-mode", "classic"
    )

    assert manifest["adr"]["inactive_reason"] == "no_adr_index"
    assert manifest["topsis_mode"] == "classic"
    assert manifest["data_provenance"] == "fixture"
    assert manifest["settings"]["topsis_mode"] == "classic"


def test_adr_index_as_a_json_file(tmp_path: Path) -> None:
    index = tmp_path / "adr_index.json"
    index.write_text(json.dumps(adr_index_document()), encoding="utf-8")
    manifest = run_script(tmp_path / "out", "--adr-index", str(index))

    assert manifest["adr"]["active"] is True


def test_source_paths_mapping_is_recorded(tmp_path: Path) -> None:
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps({"data_provenance": "manual-mapping", "elements": {"gateway": ["src/gw/**"]}}),
        encoding="utf-8",
    )
    manifest = run_script(tmp_path / "out", "--source-paths", str(mapping))

    assert manifest["inputs"]["path_mapping"] == "manual-mapping"
    assert manifest["inputs"]["source_paths_hash"].startswith("sha256:")


def test_script_ranks_like_the_service(tmp_path: Path) -> None:
    run_script(tmp_path / "script", "--adr-index", str(FIXTURES / "adr"))
    service = DegradationScoringService(default_config(outputs_root=tmp_path / "service"))
    direct = service.rank(
        load_fixture("events/fixture_events.v1.json"),
        load_fixture("graphs/fixture_release_package.v1.5.0.json"),
        run_id="script-run",
        data_provenance=DataProvenance.FIXTURE,
        adr_document=adr_index_document(),
    )
    written = tmp_path / "script" / "c4-fixture-shop" / "script-run" / "c4_report.json"

    assert written.read_bytes() == direct.outputs.report_json.read_bytes()


def test_history_source_only_with_a_repository(tmp_path: Path) -> None:
    without = c4_rank.parse_args(["--events", "e", "--graph", "g"])
    with_repo = c4_rank.parse_args(["--events", "e", "--graph", "g", "--repo", str(tmp_path)])

    assert c4_rank.history_ports(without) == {}
    assert isinstance(c4_rank.history_ports(with_repo)["history_source"], PyDrillerHistorySource)


def test_code_commit_names_the_checkout() -> None:
    commit = c4_rank.code_commit()

    assert commit is None or len(commit.removesuffix("-dirty")) == 40


def test_events_and_graph_are_required() -> None:
    with pytest.raises(SystemExit):
        c4_rank.parse_args(["--graph", "g"])
