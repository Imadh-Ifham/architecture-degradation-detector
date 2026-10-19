# Tests for the degradation scoring service (C4-T16b, T19, T20): layers 1-3 on the fixtures, the
# plain rows saved for inspection (c4_scoring_run, c4_event_ingestion, c4_event_features,
# c4_event_scores), the scoring engine's input (C4-T17), and rank() with report and manifest.

import json
import os
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest

from app.components import degradation_scoring
from app.components.degradation_scoring.features.models import HotspotFeatures
from app.components.degradation_scoring.reporting.manifest import file_hash
from app.components.degradation_scoring.service import (
    DegradationScoringService,
    RankRun,
    report_view,
    scoring_inputs,
)
from app.domain.severity_report import DataProvenance, Dimension, SeverityReportV1
from app.shared.canonical_json import content_hash
from tests.components.degradation_scoring.support import (
    FIXTURES,
    FakeRunRepository,
    adr_index_document,
    default_config,
    load_fixture,
)

PAYLOADS: list[Any] = load_fixture("events/fixture_events.v1.json")
GRAPH_DOC = load_fixture("graphs/fixture_release_package.v1.5.0.json")
EXPECTED: dict[str, Any] = load_fixture("fixture_expected.json")
DESIGNED_AV: dict[str, Any] = load_fixture("adr/adr_links.v1.json")["designed_av"]


def run(**kwargs: Any) -> tuple[Any, FakeRunRepository]:
    repo = FakeRunRepository()
    service = DegradationScoringService(default_config(), run_repository=repo)
    result = service.run_features(
        PAYLOADS, GRAPH_DOC, run_id="test-run", data_provenance="fixture", **kwargs
    )
    return result, repo


def test_package_exports_only_the_service() -> None:
    assert degradation_scoring.__all__ == ["DegradationScoringService"]
    assert degradation_scoring.DegradationScoringService is DegradationScoringService


def test_run_row_has_the_designed_counts() -> None:
    result, repo = run()
    ((run_row, _, _, _),) = repo.saved
    counts = EXPECTED["counts"]

    assert (result.system_id, result.release_id) == ("c4-fixture-shop", "v1.5.0")
    assert run_row["run_id"] == "test-run"
    assert run_row["payloads"] == counts["payloads"]
    assert run_row["ranked"] == counts["ranked"]
    assert run_row["skipped"] == sum(counts["skipped"].values())
    assert run_row["quarantined"] == sum(counts["quarantined"].values())
    assert run_row["resolution_rate"] == counts["resolution_rate"]
    assert run_row["data_provenance"] == "fixture"


def test_one_ingestion_row_per_payload_in_order() -> None:
    _, repo = run()
    ((_, rows, _, _),) = repo.saved

    assert [row["payload_index"] for row in rows] == list(range(len(PAYLOADS)))
    designed = {e["event_id"]: e["outcome"] for e in EXPECTED["events"]}
    for row in rows:
        if row["event_id"] in designed:
            outcome, _, reason = designed[row["event_id"]].partition(":")
            assert row["outcome"] == outcome, row["event_id"]
            assert (row["reason"] or "") == reason, row["event_id"]


def test_malformed_payloads_keep_their_position() -> None:
    _, repo = run()
    ((_, rows, _, _),) = repo.saved

    for malformed in EXPECTED["malformed"]:
        row = rows[malformed["index"]]
        assert row["outcome"] == "quarantined"
        assert row["reason"] == "malformed_payload"
        assert row["event_id"] == malformed["event_id"]
        assert row["detail"]


def test_ranked_rows_carry_nodes_and_resolution() -> None:
    _, repo = run()
    ((_, rows, _, _),) = repo.saved
    by_id = {row["event_id"]: row for row in rows}

    cycle = by_id["DEG-C4FX-R02-0001"]
    assert cycle["nodes"] == sorted(EXPECTED["graph"]["cycle"])
    assert (cycle["resolution_status"], cycle["resolution_confidence"]) == ("exact", 1.0)
    prefix = by_id["DEG-C4FX-R02-0007"]
    assert (prefix["resolution_status"], prefix["resolution_confidence"]) == (
        "prefix_fallback",
        0.7,
    )
    unresolved = by_id["DEG-C4FX-R02-0009"]
    assert (unresolved["outcome"], unresolved["reason"]) == ("quarantined", "unresolved_element")
    assert unresolved["nodes"] == []


def test_feature_rows_without_repo_or_adr_index() -> None:
    result, repo = run()
    ((run_row, _, rows, _),) = repo.saved

    assert len(rows) == EXPECTED["counts"]["ranked"]
    assert (run_row["hotspot_active"], run_row["hotspot_inactive_reason"]) == (
        False,
        "no_repository",
    )
    assert (run_row["adr_active"], run_row["adr_inactive_reason"]) == (False, "no_adr_index")
    for row, features in zip(rows, result.features.events, strict=True):
        assert row["br_pagerank"] == features.blast_radius.pagerank
        assert row["ps_growth_slope"] == features.persistence.growth_slope
        assert row["eh_churn_decayed"] is None
        assert row["av_weight"] is None


def test_feature_rows_with_the_fixture_adr_index() -> None:
    _, repo = run(adr_document=adr_index_document())
    ((run_row, _, rows, _),) = repo.saved

    details = run_row["details"]
    assert isinstance(details, dict)
    assert run_row["adr_active"]
    assert details["adr_status_weights"]["accepted"] == 1.0
    got = {row["event_id"]: row["av_weight"] for row in rows}
    assert got == pytest.approx({event_id: d["av"] for event_id, d in DESIGNED_AV.items()})


def test_without_a_repository_nothing_is_saved() -> None:
    service = DegradationScoringService(default_config())

    result = service.run_features(PAYLOADS, GRAPH_DOC, run_id="r", data_provenance="fixture")

    assert len(result.features.events) == EXPECTED["counts"]["ranked"]


def test_every_row_column_exists_in_the_tables() -> None:
    from app.infrastructure.postgres.models.c4_scoring_run import (
        c4_event_features,
        c4_event_ingestion,
        c4_event_scores,
        c4_scoring_run,
    )

    _, repo = run(adr_document=adr_index_document())
    ((run_row, ingestion, features, scores),) = repo.saved

    assert set(run_row) == set(c4_scoring_run.c.keys())
    assert set(ingestion[0]) == set(c4_event_ingestion.c.keys())
    assert set(features[0]) == set(c4_event_features.c.keys())
    assert set(scores[0]) == set(c4_event_scores.c.keys())


def test_scoring_inputs_match_the_saved_feature_rows() -> None:
    result, repo = run(adr_document=adr_index_document())
    ((_, _, rows, _),) = repo.saved
    active, events = scoring_inputs(result.features)
    assert active == [Dimension.BLAST_RADIUS, Dimension.ADR_VIOLATION, Dimension.PERSISTENCE]
    for row, item in zip(rows, events, strict=True):
        assert item.event_id == row["event_id"]
        assert item.values == {key: row[key] for key in item.values}
        assert not any(key.startswith("eh_") for key in item.values)


def test_scoring_inputs_with_hotspot_active() -> None:
    result, _ = run()
    hotspot = HotspotFeatures(
        churn_decayed=4.5,
        authors=2,
        coupling=1,
        bugfix_ratio=0.5,
        commits=2,
        from_release="v1.4.0",
        to_release="v1.5.0",
        first_seen_fallback=True,
        paths_available=True,
    )
    features = result.features.model_copy(
        update={
            "hotspot": result.features.hotspot.model_copy(update={"active": True}),
            "events": [e.model_copy(update={"hotspot": hotspot}) for e in result.features.events],
        }
    )
    active, events = scoring_inputs(features)
    assert active == [Dimension.BLAST_RADIUS, Dimension.HOTSPOT, Dimension.PERSISTENCE]
    assert events[0].values["eh_churn_decayed"] == 4.5
    assert events[0].values["eh_coupling"] == 1.0


def test_score_rows_follow_the_ranking_with_inactive_criteria_off() -> None:
    result, repo = run()
    ((_, _, features, scores),) = repo.saved

    assert [row["rank"] for row in scores] == list(range(1, len(features) + 1))
    assert {row["event_id"] for row in scores} == {row["event_id"] for row in features}
    assert [row["event_id"] for row in scores] == [r.event_id for r in result.scoring.ranking]
    for row in scores:
        assert row["av_normalized"] is None and row["eh_normalized"] is None  # both off
        assert (row["av_weight"], row["av_contribution"]) == (0.0, 0.0)
        values = cast(dict[str, float], row)
        assert values["br_weight"] + values["ps_weight"] == pytest.approx(1.0)
        assert values["br_contribution"] + values["ps_contribution"] == pytest.approx(1.0)
        assert row["br_normalized"] is not None


def test_run_row_details_record_how_the_run_was_scored() -> None:
    _, repo = run(adr_document=adr_index_document())
    ((run_row, _, _, scores),) = repo.saved
    scoring = cast(dict[str, Any], run_row["details"])["scoring"]

    assert scoring["topsis_mode"] == "fixed_reference"
    assert scoring["weights_version"] == "ahp_v1"
    assert scoring["weights_provenance"] == "provisional-author-elicited"
    assert round(scoring["ahp_cr"], 2) == 0.01
    assert scoring["normalization"] == "minmax_small_n"
    assert scoring["calibration_frozen"] is False
    assert "br_fan_in_ratio" in scoring["normalization_bounds"]
    assert all(row["av_normalized"] is not None for row in scores)  # AV on in this run


# rank(): the full run with report, HTML and manifest (C4-T20)

GOLDEN = FIXTURES / "golden" / "fixture_report.v1.json"
REPORT_SCHEMA = (
    Path(degradation_scoring.__file__).parent / "docs" / "schemas" / "severity_report.schema.json"
)


def rank(tmp_path: Path, run_id: str = "golden", **kwargs: Any) -> RankRun:
    config_updates = kwargs.pop("config", {})
    service = DegradationScoringService(
        default_config(outputs_root=tmp_path, **config_updates),
        history_source=kwargs.pop("history_source", None),
    )
    return service.rank(
        PAYLOADS, GRAPH_DOC, run_id=run_id, data_provenance=DataProvenance.FIXTURE, **kwargs
    )


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_close(actual: Any, expected: Any, where: str = "$") -> None:
    # equal JSON, floats within 1e-9 (last-bit noise across platforms)
    if isinstance(expected, float) and isinstance(actual, (int, float)):
        assert actual == pytest.approx(expected, rel=1e-9, abs=1e-12), where
    elif isinstance(expected, dict):
        assert isinstance(actual, dict), where
        assert list(actual) == list(expected), where
        for key in expected:
            assert_close(actual[key], expected[key], f"{where}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list), where
        assert len(actual) == len(expected), where
        for i, (a, e) in enumerate(zip(actual, expected, strict=True)):
            assert_close(a, e, f"{where}[{i}]")
    else:
        assert actual == expected, where


def test_rank_writes_the_run_files_under_system_and_run_id(tmp_path: Path) -> None:
    result = rank(tmp_path, adr_document=adr_index_document())
    directory = tmp_path / "c4-fixture-shop" / "golden"

    assert result.outputs.directory == directory
    assert sorted(p.name for p in directory.iterdir()) == [
        "c4_quarantine.json",
        "c4_report.html",
        "c4_report.json",
        "c4_run_manifest.json",
    ]


def test_rank_report_is_schema_valid(tmp_path: Path) -> None:
    result = rank(tmp_path, adr_document=adr_index_document())
    data = read(result.outputs.report_json)

    jsonschema.validate(data, read(REPORT_SCHEMA))
    assert SeverityReportV1.model_validate(data) == result.report
    assert data["schema_version"] == "1.1.0"
    assert data["weights_provenance"] == "provisional-author-elicited"
    assert data["data_provenance"] == "fixture"


def test_rank_report_follows_the_fixture_design(tmp_path: Path) -> None:
    result = rank(tmp_path, adr_document=adr_index_document())
    report, counts = result.report, EXPECTED["counts"]

    assert [r.rank for r in report.records] == list(range(1, counts["ranked"] + 1))
    assert [r.event_id for r in report.records] == [r.event_id for r in result.run.scoring.ranking]
    assert len(report.skipped) == sum(counts["skipped"].values())
    assert len(report.quarantined) == sum(counts["quarantined"].values())
    assert report.resolution_rate == counts["resolution_rate"]
    assert report.active_dimensions == [
        Dimension.BLAST_RADIUS,
        Dimension.ADR_VIOLATION,
        Dimension.PERSISTENCE,
    ]
    for record in report.records:
        av = record.dimensions[Dimension.ADR_VIOLATION]
        assert av.raw == pytest.approx(DESIGNED_AV[record.event_id]["av"])
        assert av.features["av"] == pytest.approx(DESIGNED_AV[record.event_id]["av"])
        assert not record.dimensions[Dimension.HOTSPOT].active


def test_fixture_report_matches_the_golden_file(tmp_path: Path) -> None:
    # after an intended change: run once with C4_REGENERATE_GOLDEN=1, then review the diff
    result = rank(tmp_path, adr_document=adr_index_document())
    actual = read(result.outputs.report_json)
    if os.environ.get("C4_REGENERATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_bytes(result.outputs.report_json.read_bytes())

    assert_close(actual, read(GOLDEN))


def test_identical_input_gives_identical_json(tmp_path: Path) -> None:
    first = rank(tmp_path / "a", adr_document=adr_index_document())
    same = rank(tmp_path / "b", adr_document=adr_index_document())
    other = rank(tmp_path / "c", run_id="another-run", adr_document=adr_index_document())

    text = first.outputs.report_json.read_bytes()
    assert same.outputs.report_json.read_bytes() == text
    assert other.outputs.report_json.read_bytes().replace(b"another-run", b"golden") == text
    assert same.outputs.report_html.read_bytes() == first.outputs.report_html.read_bytes()

    manifests = [read(r.outputs.manifest) for r in (first, same)]
    for manifest in manifests:
        del manifest["created_at"], manifest["settings"]["outputs_root"]
    assert manifests[0] == manifests[1]


def test_rank_without_adr_index_switches_av_off(tmp_path: Path) -> None:
    result = rank(tmp_path)
    manifest = read(result.outputs.manifest)
    html = result.outputs.report_html.read_text(encoding="utf-8")

    assert result.report.active_dimensions == [Dimension.BLAST_RADIUS, Dimension.PERSISTENCE]
    for record in result.report.records:
        av = record.dimensions[Dimension.ADR_VIOLATION]
        assert (av.active, av.weight, record.contributions[Dimension.ADR_VIOLATION]) == (
            False,
            0.0,
            0.0,
        )
    assert manifest["adr"]["active"] is False
    assert manifest["adr"]["inactive_reason"] == "no_adr_index"
    assert manifest["inputs"]["adr_index_hash"] is None
    assert sum(manifest["weights"]["used"].values()) == pytest.approx(1.0)
    assert "off (no_adr_index)" in html
    assert html.count('<span class="badge off">ADR off</span>') == len(result.report.records)


def test_rank_in_classic_mode_is_recorded(tmp_path: Path) -> None:
    result = rank(tmp_path, config={"topsis_mode": "classic"})

    assert read(result.outputs.manifest)["topsis_mode"] == "classic"
    assert "TOPSIS classic" in result.outputs.report_html.read_text(encoding="utf-8")


def test_manifest_records_inputs_parameters_and_counts(tmp_path: Path) -> None:
    adr = adr_index_document()
    result = rank(tmp_path, adr_document=adr, code_commit="abc123")
    manifest = read(result.outputs.manifest)
    counts = EXPECTED["counts"]

    assert manifest["run_id"] == "golden"
    assert manifest["code_commit"] == "abc123"
    assert manifest["inputs"]["events_hash"] == content_hash(PAYLOADS)
    assert manifest["inputs"]["graph_hash"] == content_hash(GRAPH_DOC)
    assert manifest["inputs"]["adr_index_hash"] == content_hash(adr)
    assert manifest["counts"]["payloads"] == counts["payloads"]
    assert manifest["counts"]["ranked"] == counts["ranked"]
    assert manifest["counts"]["skipped_by_reason"] == dict(sorted(counts["skipped"].items()))
    assert manifest["resolution_rate"] == counts["resolution_rate"]
    assert manifest["weights"]["version"] == "ahp_v1"
    assert manifest["weights"]["provenance"] == "provisional-author-elicited"
    assert manifest["weights"]["ahp_cr"] == result.report.ahp_cr
    assert manifest["normalization"]["mode"] == "minmax_small_n"
    assert manifest["topsis_mode"] == "fixed_reference"
    assert manifest["hotspot"]["cochange_threshold"] == 5
    assert manifest["hotspot"]["max_files_per_commit"] == 50
    assert "unmapped_line_share" in manifest["hotspot"]
    assert manifest["stand_ins"]["prefix_fallback_events"] == 1
    assert manifest["stand_ins"]["presence_fallback_events"] == counts["ranked"]
    assert manifest["seeds"] == {"seed": 42}
    assert manifest["explanation"]["run"] is False
    assert manifest["outputs"]["c4_report.json"] == file_hash(
        result.outputs.report_json.read_bytes()
    )


class TaggedHistory:
    # CommitHistorySource with tags v1.0.0..v1.5.0 (one a month) and one commit in every range,
    # touching a file that only the manual mapping gives to order-service

    def commits(self, repo_path: str, from_tag: str, to_tag: str) -> list[dict[str, Any]]:
        return [
            {
                "hash": "c1",
                "author_email": "dev@example.com",
                "committed_at": "2026-05-15T12:00:00+00:00",
                "message": "fix: order totals",
                "files": [{"path": "src/manual/order/Order.java", "added": 6, "deleted": 2}],
            }
        ]

    def tag_dates(self, repo_path: str) -> dict[str, str]:
        return {f"v1.{i}.0": f"2026-{i + 1:02d}-01T00:00:00+00:00" for i in range(6)}


def test_manual_source_paths_switch_hotspot_on_with_a_badge(tmp_path: Path) -> None:
    result = rank(
        tmp_path,
        history_source=TaggedHistory(),
        repo_path=tmp_path,
        source_paths={"order-service": ["src/manual/order/**"]},
        path_mapping="manual-mapping",
    )
    manifest = read(result.outputs.manifest)
    html = result.outputs.report_html.read_text(encoding="utf-8")
    hotspot = {
        row.event_id: row.hotspot for row in result.run.features.events if row.hotspot is not None
    }

    assert Dimension.HOTSPOT in result.report.active_dimensions
    assert manifest["hotspot"]["active"] is True
    assert manifest["inputs"]["path_mapping"] == "manual-mapping"
    assert manifest["inputs"]["source_paths_hash"] == content_hash(
        {"order-service": ["src/manual/order/**"]}
    )
    assert hotspot["DEG-C4FX-R02-0001"].commits == 1  # the cycle includes order-service
    assert hotspot["DEG-C4FX-R02-0002"].commits == 0  # common-lib
    assert "paths from manual-mapping" in html
    assert "unmapped line share" in html
    assert '<span class="badge warn">manual mapping</span>' in html


def test_report_view_flags_by_event() -> None:
    run_result, _ = run()
    view = report_view(run_result, None)
    flags = {event_id: notes.flags for event_id, notes in view.notes.items()}

    assert "fallback: path prefix" in flags["DEG-C4FX-R02-0007"]
    assert "context uncertain" in flags["DEG-C4FX-R02-0005"]
    assert all("hotspot off" in f and "ADR off" in f for f in flags.values())
    assert view.adr_inactive_reason == "no_adr_index"
    assert view.notes["DEG-C4FX-R02-0001"].nodes == [
        "inventory-service",
        "order-service",
        "payment-service",
        "shipping-service",
    ]
