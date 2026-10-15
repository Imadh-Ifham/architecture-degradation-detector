"""C3 command line. Run from ``backend/``:  uv run python -m scripts.c3 --help

Commands are added by the task that first needs them; T-01 adds ``schemas export``, T-02
``config show``. Logs are JSON lines on stderr; command output goes to stdout.
"""

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel

from app.components.degradation_detection.config import (
    DEFAULT_CONFIG_PATH,
    ConfigError,
    load_config,
)
from app.components.degradation_detection.stub import StubService
from app.components.degradation_detection.stub.models import DEFAULT_SEED
from app.core.logging import configure_logging
from app.domain.audit_entry import AuditEntryV1
from app.domain.degradation_event import DegradationEventV2
from app.domain.release_package import ReleasePackageV1

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = BACKEND_ROOT / "schemas"
STUB_SYSTEM_DIR = BACKEND_ROOT / "data" / "samples" / "shopfront"
SERIES_FIXTURE_DIR = BACKEND_ROOT / "tests" / "fixtures" / "series"

CONTRACTS: dict[str, type[BaseModel]] = {
    "c3_input.schema.json": ReleasePackageV1,
    "c3_output.schema.json": DegradationEventV2,
    "c3_audit.schema.json": AuditEntryV1,
}


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


app = typer.Typer(help="C3 degradation detection.", no_args_is_help=True)
schemas_app = typer.Typer(help="JSON Schemas of the C3 contracts.", no_args_is_help=True)
config_app = typer.Typer(help="The C3 configuration.", no_args_is_help=True)
app.add_typer(schemas_app, name="schemas")
stub_app = typer.Typer(
    help="Synthetic C2 packages with planted ground truth.", no_args_is_help=True
)
app.add_typer(config_app, name="config")
app.add_typer(stub_app, name="stub")

Seed = Annotated[int, typer.Option(help="Same seed, same bytes.")]


@app.callback()
def main(
    log_level: Annotated[LogLevel, typer.Option(help="Lowest level to log.")] = LogLevel.INFO,
) -> None:
    configure_logging(log_level.value)


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


@config_app.command("show")
def show_config(
    config: Annotated[Path, typer.Option(help="YAML config file.")] = DEFAULT_CONFIG_PATH,
) -> None:
    """Print the validated configuration and its hash, as stored on every analysis run."""
    try:
        cfg = load_config(config)
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    shown = {"config_hash": cfg.config_hash, "config": cfg.model_dump(mode="json")}
    typer.echo(json.dumps(shown, indent=2, sort_keys=True))


def _write_files(out: Path, files: dict[str, str]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8", newline="\n")
    typer.echo(f"wrote {len(files)} files to {out}")


@stub_app.command("generate")
def generate_stub(
    out: Annotated[Path, typer.Option(help="Directory to write to.")] = STUB_SYSTEM_DIR,
    seed: Seed = DEFAULT_SEED,
) -> None:
    """Write the `shopfront` release packages and ground_truth.yaml."""
    _write_files(out, StubService().generate(seed).system_files)


@stub_app.command("series")
def generate_series(
    out: Annotated[Path, typer.Option(help="Directory to write to.")] = SERIES_FIXTURE_DIR,
    seed: Seed = DEFAULT_SEED,
) -> None:
    """Write the bare series fixtures used by the trend tests."""
    _write_files(out, StubService().generate(seed).series_files)


if __name__ == "__main__":
    app()
