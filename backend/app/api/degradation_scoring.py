# Degradation scoring (C4) API: scores the run degradation detection just made (the pipeline's
# Score phase), lists saved rank runs and returns a run's severity report. Composition root:
# the only place that knows the hand-over and the reports are files, where the full history
# clone is (<repositories_root>/c4-history/<repository name>) and where the hand-made
# element -> source path mappings are (configs/scoring/source_paths/<repository name>.json).

import json
import re
import subprocess
from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.exc import OperationalError

from app.api.schemas.degradation_scoring import ScoringRunRequest, ScoringRunResponse
from app.components.degradation_scoring.service import (
    AmbiguousRunError,
    DegradationScoringService,
    HandoverNotFoundError,
    SavedReportError,
    service_from_settings,
)
from app.core.config import BACKEND_ROOT, settings
from app.domain.severity_report import SeverityReportV1
from app.infrastructure.scoring_reports import DetectionHandoverFiles, ScoringReportFileStore

router = APIRouter(prefix="/degradation-scoring", tags=["Severity scoring"])

HISTORY_FOLDER = "c4-history"
SOURCE_PATHS_DIR = BACKEND_ROOT / "configs" / "scoring" / "source_paths"
REPOSITORY_HASH = re.compile(r"-[0-9a-f]{12}$")


@lru_cache
def get_degradation_scoring_service() -> DegradationScoringService:
    # reads the reports under settings.scoring_outputs_root; tests override this dependency
    return service_from_settings(
        settings, saved_reports=ScoringReportFileStore(settings.scoring_outputs_root)
    )


def get_run_service() -> DegradationScoringService:  # pragma: no cover - real adapters
    # the service a scoring run needs: detection's hand-over, the saved reports, Postgres for
    # the run rows and the mining cache, and the git history source; tests override this
    from sqlalchemy.orm import sessionmaker

    from app.infrastructure.git.history import PyDrillerHistorySource
    from app.infrastructure.postgres.database import engine
    from app.infrastructure.postgres.repositories.mining_cache_repository import (
        PostgresMiningCache,
    )
    from app.infrastructure.postgres.repositories.scoring_run_repository import (
        PostgresScoringRunRepository,
    )

    sessions = sessionmaker(bind=engine)
    return service_from_settings(
        settings,
        saved_reports=ScoringReportFileStore(settings.scoring_outputs_root),
        detection_handover=DetectionHandoverFiles(settings.degradation_outputs_root),
        run_repository=PostgresScoringRunRepository(sessions),
        mining_cache=PostgresMiningCache(sessions),
        history_source=PyDrillerHistorySource(),
    )


def repository_name(repository_id: str) -> str:
    # "microservices-demo-65bf2e173bd5" -> "microservices-demo" (the url hash dropped)
    return REPOSITORY_HASH.sub("", repository_id)


def history_inputs(repository_id: str) -> dict[str, Any]:
    # the full clone and the manual mapping, when both are there; else hotspot is off
    name = repository_name(repository_id)
    clone = settings.repositories_root / HISTORY_FOLDER / name
    mapping = SOURCE_PATHS_DIR / f"{name}.json"
    if not ((clone / ".git").exists() and mapping.is_file()):
        return {}
    document = json.loads(mapping.read_text(encoding="utf-8"))
    return {
        "repo_path": clone,
        "source_paths": document["elements"],
        "path_mapping": document.get("data_provenance", "manual-mapping"),
    }


def code_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=BACKEND_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


ScoringService = Annotated[DegradationScoringService, Depends(get_degradation_scoring_service)]
RunService = Annotated[DegradationScoringService, Depends(get_run_service)]
RunId = Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$", max_length=128)]


@router.post(
    "/runs",
    response_model=ScoringRunResponse,
    summary="Score a detection run",
    description="Ranks the events of one degradation detection run (its events.json and the "
    "release package of its last release, as detection left them) and saves the run as "
    "score-<detection run id>, files and Postgres rows. A run already scored is returned "
    "as it is. Hotspot uses the repository's git history when a full clone and a source "
    "path mapping exist; otherwise it is off.",
    responses={
        404: {"description": "That detection run left no hand-over files."},
        503: {"description": "The database could not be reached."},
    },
)
def score_detection_run(request: ScoringRunRequest, service: RunService) -> ScoringRunResponse:
    try:
        run = service.score_detection(
            request.repository_id,
            request.detection_run_id,
            code_commit=code_commit(),
            **history_inputs(request.repository_id),
        )
    except HandoverNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except OperationalError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The scoring store (PostgreSQL) could not be reached. Is it running?",
        ) from error
    return ScoringRunResponse.model_validate(run.model_dump())


@router.get(
    "/runs",
    response_model=list[ScoringRunResponse],
    summary="List saved scoring runs",
    description="Every saved rank run, newest first. Empty until a run has been written "
    "with scripts/c4_rank.py.",
)
def list_runs(service: ScoringService) -> list[ScoringRunResponse]:
    return [ScoringRunResponse.model_validate(run.model_dump()) for run in service.runs()]


@router.get(
    "/runs/{run_id}/report",
    response_model=SeverityReportV1,
    summary="Get a run's severity report",
    description="The saved c4_report.json of one run (SeverityReportV1, ranked records).",
    responses={
        404: {"description": "No saved run has this id."},
        409: {"description": "Two systems hold a run with this id."},
        500: {"description": "The saved report does not match SeverityReportV1."},
    },
)
def get_report(run_id: RunId, service: ScoringService) -> SeverityReportV1:
    try:
        report = service.report(run_id)
    except AmbiguousRunError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except SavedReportError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error)
        ) from error
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no saved run {run_id!r}"
        )
    return report
