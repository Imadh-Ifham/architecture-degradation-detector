"""C3 command line. Run from ``backend/``:  uv run python -m scripts.c3 --help

Commands are added by the task that first needs them; T-01 adds ``schemas export``, T-02
``config show``, T-03 ``stub``, T-04 ``ingest``, T-07 ``detect``, T-08 ``align``, T-10
``series``. Logs are JSON lines on stderr; command output goes to stdout.

``ingest`` stores into and ``detect`` / ``align`` / ``series`` read from PostgreSQL
(``docker compose up -d``, then ``uv run alembic upgrade head``). The database modules are imported
only when a command needs them, so every other command works without a ``.env``.
"""

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel

from app.components.degradation_detection.config import (
    DEFAULT_CATALOG_PATH,
    DEFAULT_CONFIG_PATH,
    C3Config,
    ConfigError,
    load_config,
)
from app.components.degradation_detection.detection import DetectionService
from app.components.degradation_detection.ingestion import IngestService
from app.components.degradation_detection.ingestion.models import (
    IngestOutcome,
    IngestReport,
    IngestStatus,
    RawPackage,
)
from app.components.degradation_detection.models import Timeline
from app.components.degradation_detection.ports import ReleaseRepository
from app.components.degradation_detection.stub import StubService
from app.components.degradation_detection.stub.models import DEFAULT_SEED
from app.components.degradation_detection.tracking import TrackingService
from app.components.degradation_detection.tracking.alignment_sample import alignment_sample_csv
from app.components.degradation_detection.tracking.models import TrackingResult
from app.components.degradation_detection.tracking.series_csv import series_csv
from app.core.logging import configure_logging
from app.domain.audit_entry import AuditEntryV1
from app.domain.canonical_release import GateStatus
from app.domain.degradation_event import DegradationEventV2, Scope
from app.domain.release_package import ReleasePackageV1
from app.shared.clock import SystemClock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = BACKEND_ROOT / "schemas"
STUB_SYSTEM_DIR = BACKEND_ROOT / "data" / "samples" / "shopfront"
SERIES_FIXTURE_DIR = BACKEND_ROOT / "tests" / "fixtures" / "series"
OUT_DIR = BACKEND_ROOT / "out"

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
ConfigFile = Annotated[Path, typer.Option(help="YAML config file.")]
CatalogFile = Annotated[Path, typer.Option(help="YAML detector catalog.")]


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
    config: ConfigFile = DEFAULT_CONFIG_PATH, catalog: CatalogFile = DEFAULT_CATALOG_PATH
) -> None:
    """Print the validated configuration and its hash, as stored on every analysis run."""
    cfg = _load_config_or_exit(config, catalog)
    shown = {"config_hash": cfg.config_hash, "config": cfg.model_dump(mode="json")}
    typer.echo(json.dumps(shown, indent=2, sort_keys=True))


def _load_config_or_exit(path: Path, catalog: Path = DEFAULT_CATALOG_PATH) -> C3Config:
    try:
        return load_config(path, catalog)
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
    config: ConfigFile = DEFAULT_CONFIG_PATH,
) -> None:
    """Validate, normalise, gate and store C2 release packages. Re-running is a no-op."""
    cfg = _load_config_or_exit(config)
    packages = _read_packages(path, cfg.ingest.max_package_bytes)
    report = IngestService(release_repository(), SystemClock(), cfg).ingest(packages)
    for outcome in report.outcomes:
        typer.echo(_outcome_line(outcome))
    typer.echo(_summary_line(report))


def _timeline_or_exit(system: str, cfg: C3Config) -> Timeline:
    timeline = IngestService(release_repository(), SystemClock(), cfg).timeline(system)
    if not timeline.entries:
        typer.echo(f"no releases on the timeline of system {system!r}; run `c3 ingest` first")
        raise typer.Exit(code=1)
    return timeline


@app.command("detect")
def detect(
    system: Annotated[str, typer.Option(help="System id, as ingested.")],
    config: ConfigFile = DEFAULT_CONFIG_PATH,
    catalog: CatalogFile = DEFAULT_CATALOG_PATH,
) -> None:
    """Print the anti-pattern instances M2 finds in every release on the system's timeline."""
    cfg = _load_config_or_exit(config, catalog)
    timeline = _timeline_or_exit(system, cfg)

    detection = DetectionService(cfg)
    typer.echo(f"{'release':<10} {'gate':<12} {'anti_pattern_type':<20} members")
    total = 0
    for entry in timeline.entries:
        r = entry.release
        instances = detection.detect(r).instances
        total += len(instances)
        rows = [(i.anti_pattern_type, ",".join(i.members)) for i in instances] or [("-", "-")]
        for anti_pattern_type, members in rows:
            typer.echo(
                f"{r.release_id:<10} {r.gate_status.value:<12} {anti_pattern_type:<20} {members}"
            )
    typer.echo(f"{len(timeline.entries)} releases, {total} instances")


def _track_or_exit(system: str, cfg: C3Config) -> tuple[Timeline, TrackingResult]:
    """M2 on every release of the timeline, then M3 (T-13 replaces this with ``c3 run``)."""
    timeline = _timeline_or_exit(system, cfg)
    detection = DetectionService(cfg)
    detections = [detection.detect(entry.release) for entry in timeline.entries]
    return timeline, TrackingService(cfg).track(timeline, detections)


@app.command("align")
def align(
    system: Annotated[str, typer.Option(help="System id, as ingested.")],
    config: ConfigFile = DEFAULT_CONFIG_PATH,
    catalog: CatalogFile = DEFAULT_CATALOG_PATH,
    out: Annotated[
        Path | None,
        typer.Option(help="CSV to write. Default: out/<system>/alignment_sample.csv."),
    ] = None,
) -> None:
    """Print element lineages, renames and instance tracks; write the alignment sample."""
    timeline, result = _track_or_exit(system, _load_config_or_exit(config, catalog))

    typer.echo(f"{'lineage_id':<34} {'kind':<10} {'first':<10} {'last':<10} element_ids")
    for lin in result.lineages:
        ids = list(dict.fromkeys(m.element_id for m in lin.members))  # each id once, in order
        first, last = lin.members[0].release_id, lin.members[-1].release_id
        typer.echo(f"{lin.lineage_id:<34} {lin.kind:<10} {first:<10} {last:<10} {' > '.join(ids)}")
    for event in result.events:
        typer.echo(
            f"{event.release_id:<10} {event.event_type.value} {event.method.value} "
            f"{event.lineage_id} {';'.join(event.from_element_ids)} "
            f"{';'.join(event.to_element_ids)}"
        )

    typer.echo(
        f"{'track_id':<46} {'first':<10} {'last':<10} {'end':<9} {'lifecycle':<11} member_counts"
    )
    for track in result.tracks:
        first, last = track.occurrences[0].release_id, track.occurrences[-1].release_id
        counts = ">".join(str(len(o.members)) for o in track.occurrences)
        lifecycle = track.lifecycle.value if track.lifecycle else "-"
        typer.echo(
            f"{track.track_id:<46} {first:<10} {last:<10} {track.end.value:<9} "
            f"{lifecycle:<11} {counts}"
        )

    path = out or OUT_DIR / system / "alignment_sample.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(alignment_sample_csv(result), encoding="utf-8", newline="\n")
    typer.echo(
        f"{len(timeline.entries)} releases, {len(result.lineages)} lineages, "
        f"{len(result.events)} renames, {len(result.decisions)} decisions, "
        f"{len(result.tracks)} instance tracks; wrote {path}"
    )


@app.command("series")
def series(
    system: Annotated[str, typer.Option(help="System id, as ingested.")],
    config: ConfigFile = DEFAULT_CONFIG_PATH,
    catalog: CatalogFile = DEFAULT_CATALOG_PATH,
    out: Annotated[
        Path | None,
        typer.Option(help="CSV to write. Default: out/<system>/series.csv."),
    ] = None,
) -> None:
    """Write every ELEMENT, INSTANCE and SYSTEM series M4 would test, one row per point."""
    timeline, result = _track_or_exit(system, _load_config_or_exit(config, catalog))

    path = out or OUT_DIR / system / "series.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(series_csv(result.series), encoding="utf-8", newline="\n")
    counts = {
        scope: sum(1 for s in result.series if s.scope is scope)
        for scope in (Scope.ELEMENT, Scope.INSTANCE, Scope.SYSTEM)
    }
    by_scope = ", ".join(f"{n} {scope.value}" for scope, n in counts.items())
    typer.echo(
        f"{len(timeline.entries)} releases; series: {by_scope}; "
        f"{sum(len(s.points) for s in result.series)} points; wrote {path}"
    )


if __name__ == "__main__":
    app()
