"""C3 command line. Run from ``backend/``:  uv run python -m scripts.c3 --help

Commands are added by the task that first needs them; T-01 adds ``schemas export``, T-02
``config show``. Logs are JSON lines on stderr; command output goes to stdout.
"""

import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel

from app.domain.audit_entry import AuditEntryV1
from app.domain.degradation_event import DegradationEventV2
from app.domain.release_package import ReleasePackageV1

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = BACKEND_ROOT / "schemas"

CONTRACTS: dict[str, type[BaseModel]] = {
    "c3_input.schema.json": ReleasePackageV1,
    "c3_output.schema.json": DegradationEventV2,
    "c3_audit.schema.json": AuditEntryV1,
}

app = typer.Typer(help="C3 degradation detection.", no_args_is_help=True)
schemas_app = typer.Typer(help="JSON Schemas of the C3 contracts.", no_args_is_help=True)
app.add_typer(schemas_app, name="schemas")


def render_schemas() -> dict[str, str]:
    """Return file name -> JSON Schema text, generated from the contract models."""
    return {
        name: json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
        for name, model in CONTRACTS.items()
    }


@schemas_app.command("export")
def export_schemas(
    out: Annotated[Path, typer.Option(help="Directory to write the schema files to.")] = SCHEMA_DIR,
) -> None:
    """Generate the schema files from the Pydantic models. Never edit them by hand."""
    out.mkdir(parents=True, exist_ok=True)
    for name, text in render_schemas().items():
        (out / name).write_text(text, encoding="utf-8", newline="\n")
        typer.echo(f"wrote {out / name}")


if __name__ == "__main__":
    app()
