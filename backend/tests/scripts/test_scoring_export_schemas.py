# Tests for the C4 schema export script.
# schema files must equal what the script generates
# a contract change that forgot to regenerate them fails here

import json
from pathlib import Path

from scripts.scoring_export_schemas import SCHEMA_DIR, main, render_schemas, stale_files


def test_committed_schemas_are_up_to_date() -> None:
    assert stale_files(SCHEMA_DIR) == [], (
        "regenerate with: uv run python -m scripts.scoring_export_schemas"
    )


def test_export_writes_one_parseable_schema_per_contract(tmp_path: Path) -> None:
    assert main(["--out", str(tmp_path)]) == 0

    written = sorted(path.name for path in tmp_path.iterdir())
    assert written == sorted(render_schemas())
    schema = json.loads((tmp_path / "severity_report.schema.json").read_text(encoding="utf-8"))
    assert schema["title"] == "SeverityReportV1"


def test_export_is_byte_stable(tmp_path: Path) -> None:
    main(["--out", str(tmp_path)])
    first = (tmp_path / "severity_report.schema.json").read_bytes()
    main(["--out", str(tmp_path)])

    assert (tmp_path / "severity_report.schema.json").read_bytes() == first
    assert b"\r\n" not in first


def test_check_reports_missing_and_changed_files(tmp_path: Path) -> None:
    assert main(["--check", "--out", str(tmp_path)]) == 1

    main(["--out", str(tmp_path)])
    assert main(["--check", "--out", str(tmp_path)]) == 0

    (tmp_path / "severity_report.schema.json").write_text("{}", encoding="utf-8")
    assert main(["--check", "--out", str(tmp_path)]) == 1
