# Writes saved runs (report + manifest) into a temporary outputs root, like rank() does, for
# the read-side query, file store and API tests. Built from the golden fixture report.

import json
from pathlib import Path
from typing import Any

GOLDEN = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "degradation_scoring"
    / "golden"
    / "fixture_report.v1.json"
)


def golden_report() -> dict[str, Any]:
    report: dict[str, Any] = json.loads(GOLDEN.read_text(encoding="utf-8"))
    return report


def manifest(report: dict[str, Any], created_at: str) -> dict[str, Any]:
    # the manifest fields the run list uses, as manifest_facts() writes them
    return {
        "run_id": report["run_id"],
        "system_id": report["system_id"],
        "release_id": report["release_id"],
        "data_provenance": report["data_provenance"],
        "active_dimensions": report["active_dimensions"],
        "counts": {
            "payloads": 17,
            "ranked": len(report["records"]),
            "skipped": len(report["skipped"]),
            "quarantined": len(report["quarantined"]),
            "skipped_by_reason": {},
            "quarantined_by_reason": {},
        },
        "resolution_rate": report["resolution_rate"],
        "created_at": created_at,
    }


def save_run(
    root: Path,
    run_id: str,
    created_at: str = "2026-10-19T10:00:00+00:00",
    system_id: str = "c4-fixture-shop",
) -> dict[str, Any]:
    report = golden_report() | {"run_id": run_id, "system_id": system_id}
    folder = root / system_id / run_id
    folder.mkdir(parents=True)
    (folder / "c4_report.json").write_text(json.dumps(report), encoding="utf-8")
    (folder / "c4_run_manifest.json").write_text(
        json.dumps(manifest(report, created_at)), encoding="utf-8"
    )
    return report
