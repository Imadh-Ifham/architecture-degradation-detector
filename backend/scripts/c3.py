"""C3 command line. Run from ``backend/``:  uv run python -m scripts.c3 --help

Commands are added by the task that first needs them; T-01 adds ``schemas export``, T-02
``config show``, T-03 ``stub``, T-04 ``ingest``. Logs are JSON lines on stderr; command output
goes to stdout.

``ingest`` stores into PostgreSQL (``docker compose up -d``, then ``uv run alembic upgrade
head``). The database modules are imported only when a command needs them, so every other
command works without a ``.env``.
"""

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel

from app.components.degradation_detection.config import (
    DEFAULT_CONFIG_PATH,
    C3Config,
    ConfigError,
    load_config,
)
from app.components.degradation_detection.ingestion import IngestService
from app.components.degradation_detection.ingestion.models import (
    IngestOutcome,
    IngestReport,
    IngestStatus,
    RawPackage,
)
from app.components.degradation_detection.ports import ReleaseRepository
from app.components.degradation_detection.stub import StubService
from app.components.degradation_detection.stub.models import DEFAULT_SEED
from app.core.logging import configure_logging
from app.domain.audit_entry import AuditEntryV1
from app.domain.canonical_release import GateStatus
from app.domain.degradation_event import DegradationEventV2
from app.domain.release_package import ReleasePackageV1
from app.shared.clock import SystemClock

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
    cfg = _load_config_or_exit(config)
    shown = {"config_hash": cfg.config_hash, "config": cfg.model_dump(mode="json")}
    typer.echo(json.dumps(shown, indent=2, sort_keys=True))


def _load_config_or_exit(path: Path) -> C3Config:
    try:
        return load_config(path)
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc


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


def release_repository() -> ReleaseRepository:
    """The PostgreSQL release store. Tests replace this function with an in-memory fake."""
    from app.infrastructure.postgres.database import SessionLocal
    from app.infrastructure.postgres.repositories.c3_release_repository import (
        PostgresReleaseRepository,
    )

    return PostgresReleaseRepository(SessionLocal)


def _read_packages(path: Path, max_bytes: int) -> list[RawPackage]:
    """Every ``*.json`` file of a directory (not recursive), or the one file given.

    At most one byte over the size cap is read, enough for ingestion to reject the package
    without loading a huge file into memory.
    """
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    packages = []
    for file in files:
        with file.open("rb") as handle:
            packages.append(RawPackage(source=file.name, data=handle.read(max_bytes + 1)))
    return packages


def _outcome_line(outcome: IngestOutcome) -> str:
    if outcome.status is IngestStatus.REJECTED:
        return f"{outcome.status:<9} {outcome.source}  {outcome.reason}: {outcome.detail}"
    gate_status = outcome.gate_status.value if outcome.gate_status else ""
    release = f"{outcome.system_id} {outcome.release_id}"
    return f"{outcome.status:<9} {outcome.source}  {release} {gate_status}"


def _summary_line(report: IngestReport) -> str:
    kept = [o for o in report.outcomes if o.status is not IngestStatus.REJECTED]
    gates = {g: sum(1 for o in kept if o.gate_status is g) for g in GateStatus}
    return (
        f"{len(report.outcomes)} packages: {report.count(IngestStatus.STORED)} stored, "
        f"{report.count(IngestStatus.UNCHANGED)} unchanged, "
        f"{report.count(IngestStatus.REJECTED)} rejected "
        f"(gate: {gates[GateStatus.ACCEPTED]} accepted, "
        f"{gates[GateStatus.DOWNWEIGHTED]} downweighted, {gates[GateStatus.EXCLUDED]} excluded)"
    )


@app.command("ingest")
def ingest(
    path: Annotated[
        Path,
        typer.Argument(
            exists=True, help="A package file, or a directory of <system>__<release>.json files."
        ),
    ],
    config: Annotated[Path, typer.Option(help="YAML config file.")] = DEFAULT_CONFIG_PATH,
) -> None:
    """Validate, normalise, gate and store C2 release packages. Re-running is a no-op."""
    cfg = _load_config_or_exit(config)
    packages = _read_packages(path, cfg.ingest.max_package_bytes)
    report = IngestService(release_repository(), SystemClock(), cfg).ingest(packages)
    for outcome in report.outcomes:
        typer.echo(_outcome_line(outcome))
    typer.echo(_summary_line(report))


if __name__ == "__main__":
    app()
