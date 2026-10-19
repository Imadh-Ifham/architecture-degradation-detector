# Export the JSON Schemas of the degradation scoring (C4) contracts.
# Generates one JSON Schema file per C4-owned contract from its Pydantic model
# writes it to app/components/degradation_scoring/docs/schemas/.
# Usage, from backend/:
#         uv run python -m scripts.scoring_export_schemas
#         uv run python -m scripts.scoring_export_schemas --check
# exit 1 if out of date

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel

from app.domain.severity_report import SeverityReportV1

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = BACKEND_ROOT / "app" / "components" / "degradation_scoring" / "docs" / "schemas"

CONTRACTS: dict[str, type[BaseModel]] = {
    "severity_report.schema.json": SeverityReportV1,
}


def render_schemas() -> dict[str, str]:
    """File name -> schema text. Keys are sorted so the output is byte-stable."""
    return {
        name: json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
        for name, model in CONTRACTS.items()
    }


def stale_files(directory: Path) -> list[str]:
    """Names of schema files that are missing or differ from the generated text."""
    return [
        name
        for name, text in render_schemas().items()
        if not (directory / name).is_file()
        or (directory / name).read_text(encoding="utf-8") != text
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export the JSON Schemas of the C4 contracts.")
    parser.add_argument("--out", type=Path, default=SCHEMA_DIR, help="Directory to write to.")
    parser.add_argument(
        "--check", action="store_true", help="Write nothing; exit 1 if a file is out of date."
    )
    args = parser.parse_args(argv)

    if args.check:
        stale = stale_files(args.out)
        for name in stale:
            print(f"out of date: {args.out / name}")
        return 1 if stale else 0

    args.out.mkdir(parents=True, exist_ok=True)
    for name, text in render_schemas().items():
        # newline="\n" keeps the committed file identical on Windows and Linux.
        (args.out / name).write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {args.out / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
