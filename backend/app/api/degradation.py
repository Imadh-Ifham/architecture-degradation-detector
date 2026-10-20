"""Degradation detection endpoints.

Description:
    Exposes the degradation detection component over HTTP: run it over every
    validated release of one repository, and read a stored run back as the
    document the drift screen draws.

    This module is the component's composition root, like `validations.py` is
    for validation: the only place that knows the release and run stores are
    PostgreSQL, that C2's published graphs are files, and which configuration
    a run from the application uses.

    **The input is C2's published graph, not a file somebody prepared.** A
    run reads the `latest.graph.json` of every validated release of the
    repository, turns each into a release package and ingests it, replacing a
    release C2 has validated again since. So "detect" always means "detect
    over the releases as they are validated now".

    A run is synchronous. Detection is deterministic code over a few releases
    and finishes in seconds; a job queue would add a state the screen has to
    poll for no gain.
"""

import json
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import OperationalError

from app.components.degradation_detection import DegradationDetectionService
from app.components.degradation_detection.config import C3Config, ConfigError, load_config
from app.components.degradation_detection.ingestion.from_validated import package_from_validated
from app.components.degradation_detection.ingestion.models import IngestReport, IngestStatus
from app.core.config import BACKEND_ROOT, settings
from app.infrastructure.validated_graph import ValidatedGraphFileStore
from app.shared.clock import SystemClock

router = APIRouter(prefix="/degradation", tags=["Degradation"])


class DegradationRunRequest(BaseModel):
    """Which repository to analyse: the identity its graphs are published under."""

    model_config = ConfigDict(
        json_schema_extra={"example": {"repository_id": "microservices-demo-58a841308994"}}
    )

    repository_id: str = Field(min_length=1)


@lru_cache(maxsize=1)
def get_config() -> C3Config:
    """The configuration API runs use (`degradation_config_path`)."""

    return load_config(settings.degradation_config_path)


@lru_cache(maxsize=1)
def get_graph_store() -> ValidatedGraphFileStore:
    """Where C2 publishes the graphs this component reads."""

    return ValidatedGraphFileStore(settings.validated_graph_root)


def get_service() -> DegradationDetectionService:
    """The component over the PostgreSQL stores.

    Imported here rather than at module level so the application starts, and
    every other route answers, on a machine where the database is not up.
    """

    from app.infrastructure.postgres.database import SessionLocal
    from app.infrastructure.postgres.repositories.c3_analysis_run_repository import (
        PostgresAnalysisRunRepository,
    )
    from app.infrastructure.postgres.repositories.c3_release_repository import (
        PostgresReleaseRepository,
    )

    return DegradationDetectionService(
        PostgresReleaseRepository(SessionLocal),
        PostgresAnalysisRunRepository(SessionLocal),
        SystemClock(),
        get_config(),
    )


def code_version() -> str:
    """The git commit of the running code, `-dirty` with local changes, else `unknown`."""

    try:
        sha, changes = (
            subprocess.run(
                ["git", *args],
                cwd=BACKEND_ROOT,
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            ).stdout.strip()
            for args in (["rev-parse", "--short", "HEAD"], ["status", "--porcelain", "-uno"])
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return f"{sha}-dirty" if changes else sha


@router.post(
    "/runs",
    summary="Detect degradation over every validated release",
    response_description=(
        "What happened to each published graph on the way in, and the stored "
        "run as the drift screen reads it."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "No release of that repository has been validated."
        },
        status.HTTP_409_CONFLICT: {
            "description": "Graphs were published, but none could go on the "
            "timeline - every one was refused or gated out. The detail lists why."
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "The configuration or the database could not be reached."
        },
    },
)
def run_detection(request: DegradationRunRequest) -> dict[str, Any]:
    """Ingest every published graph of the repository, then run detection.

    A release C2 validated again since the last run replaces the stored one;
    an unchanged one is left as it is. A graph that cannot be ingested - no
    release date, say - is reported with its reason and the rest go on.
    """

    store = get_graph_store()
    releases = store.releases(request.repository_id)
    documents = [
        document
        for release in releases
        if (document := store.read(request.repository_id, release)) is not None
    ]
    if not documents:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No release of '{request.repository_id}' has been validated yet. "
                "Validate at least one release first."
            ),
        )

    service = _service_or_503()
    with _database():
        ingest = service.ingest_validated(documents)
        try:
            result = service.run(request.repository_id, code_version=code_version())
        except LookupError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "None of the validated releases could go on the timeline.",
                    "ingest": _outcomes(ingest),
                },
            ) from error

        report = service.view(result.stored.run.run_id)

    handover = write_handover(
        request.repository_id,
        result.stored.run.run_id,
        result.files,
        _last_package(report, documents),
    )
    return {"ingest": _outcomes(ingest), "report": report | {"handover": handover}}


@router.get(
    "/runs/latest",
    summary="The latest completed run for one repository",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Detection has not been run for that repository, "
            "which is a state rather than a fault."
        }
    },
)
def read_latest_run(repository_id: str) -> dict[str, Any]:
    """Return the most recent completed run, as the drift screen reads it."""

    service = _service_or_503()
    with _database():
        run_id = service.latest_run_id(repository_id)
        if run_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Degradation has not been detected for '{repository_id}' yet.",
            )
        report = service.view(run_id)
    return report | {"handover": _handover_paths(repository_id, run_id)}


@router.get(
    "/runs/{run_id}",
    summary="One stored run",
    responses={status.HTTP_404_NOT_FOUND: {"description": "No run with that id."}},
)
def read_run(run_id: str) -> dict[str, Any]:
    """Return one stored run, as the drift screen reads it."""

    try:
        with _database():
            report = _service_or_503().view(run_id)
        return report | {"handover": _handover_paths(report["run"]["system_id"], run_id)}
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


def _service_or_503() -> DegradationDetectionService:
    try:
        return get_service()
    except (ConfigError, OSError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error


def write_handover(
    repository_id: str,
    run_id: str,
    files: dict[str, bytes],
    package: dict[str, Any] | None,
) -> dict[str, str | None]:
    """Write what the scoring phase reads, for this run and as `latest`.

    The scoring phase reads files, not this application:
    `scripts/c4_rank.py --events <events.json> --graph <release_package.json>`.
    So a run started from the screen leaves the same files a CLI run does -
    the events, the series, the report - plus the release package of the
    window's last release, which is the graph the events' element ids refer to.

    `latest` is replaced only after the run's own directory is complete, so it
    always holds one whole run.
    """

    root = settings.degradation_outputs_root / repository_id
    target = root / run_id
    for name, data in files.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    if package is not None:
        (target / RELEASE_PACKAGE).write_text(json.dumps(package, indent=2), encoding="utf-8")

    latest = root / LATEST
    staging = root / f".{LATEST}.partial"
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(target, staging)
    shutil.rmtree(latest, ignore_errors=True)
    staging.rename(latest)

    return _handover_paths(repository_id, run_id)


RELEASE_PACKAGE = "release_package.json"
LATEST = "latest"


def _handover_paths(repository_id: str, run_id: str) -> dict[str, str | None]:
    """Where the scoring phase finds this run's files, or None for one not written."""

    directory = settings.degradation_outputs_root / repository_id / run_id
    latest = settings.degradation_outputs_root / repository_id / LATEST

    def found(path: Path) -> str | None:
        return str(path) if path.is_file() else None

    return {
        "events": found(directory / "events.json"),
        "graph": found(directory / RELEASE_PACKAGE),
        "latest_events": found(latest / "events.json"),
        "latest_graph": found(latest / RELEASE_PACKAGE),
    }


def _last_package(report: dict[str, Any], documents: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The release package of the last release on the run's timeline.

    Rebuilt from the same published graph the run ingested, so it is the
    package C3 analysed, byte for byte the payload ingestion validated.
    """

    timeline = [r for r in report["releases"] if r["on_timeline"]]
    if not timeline:
        return None
    last = timeline[-1]["release_id"]
    for document in documents:
        if document.get("graph", {}).get("release_id") == last:
            return package_from_validated(document)
    return None


@contextmanager
def _database() -> Iterator[None]:
    """A database that cannot be reached is a 503 with a sentence, not a stack trace."""

    try:
        yield
    except OperationalError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The detection store (PostgreSQL) could not be reached. Is it running?",
        ) from error


def _outcomes(report: IngestReport) -> list[dict[str, Any]]:
    return [
        outcome.model_dump(mode="json") | {"accepted": outcome.status is not IngestStatus.REJECTED}
        for outcome in report.outcomes
    ]
