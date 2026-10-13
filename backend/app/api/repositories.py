"""Repository ingestion endpoints.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Exposes the repository ingestion subcomponent over HTTP: clone a
    repository onto the machine, list what is present, and remove it again.
"""

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, status

from app.components.architecture_recovery.repository_ingestion.errors import (
    InvalidRepositorySource,
    RepositoryNotFound,
)
from app.components.architecture_recovery.repository_ingestion.schemas import (
    IngestedRepositoryResponse,
    RepositoryIngestionRequest,
)
from app.components.architecture_recovery.repository_ingestion.service import (
    RepositoryIngestionService,
)
from app.components.architecture_recovery.repository_ingestion.validation import (
    redact_credentials,
)
from app.core.config import settings
from app.infrastructure.git.client import GitClient, GitCommandError


router = APIRouter(prefix="/repositories", tags=["Repositories"])


@lru_cache
def get_git_client() -> GitClient:
    """Provide a process-wide git client built from the configured timeout."""

    return GitClient(timeout_seconds=settings.git_clone_timeout_seconds)


@lru_cache
def get_repository_ingestion_service() -> RepositoryIngestionService:
    """Provide the ingestion service shared by all requests.

    Cached so the workspace settings are read once. Declared as a FastAPI
    dependency so tests can override it.
    """

    return RepositoryIngestionService(
        git_client=get_git_client(),
        root=settings.repositories_root,
    )


@router.post(
    "",
    response_model=IngestedRepositoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def ingest_repository(
    request: RepositoryIngestionRequest,
    service: RepositoryIngestionService = Depends(get_repository_ingestion_service),
) -> IngestedRepositoryResponse:
    """Clone `request.url` at `request.branch` into the workspace."""

    try:
        repository = service.ingest(request.url, request.branch)
    except InvalidRepositorySource as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error
    except GitCommandError as error:
        # git stderr is the only place the real cause appears (unknown branch,
        # authentication, network). Redact it in case a url carried credentials.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=redact_credentials(_describe_git_failure(error)),
        ) from error

    return IngestedRepositoryResponse.model_validate(repository)


@router.get("", response_model=list[IngestedRepositoryResponse])
def list_repositories(
    service: RepositoryIngestionService = Depends(get_repository_ingestion_service),
) -> list[IngestedRepositoryResponse]:
    """List every repository currently held in the workspace."""

    return [
        IngestedRepositoryResponse.model_validate(repository)
        for repository in service.list_ingested()
    ]


@router.delete("/{repository_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_repository(
    repository_id: str,
    service: RepositoryIngestionService = Depends(get_repository_ingestion_service),
) -> None:
    """Remove an ingested repository from the machine."""

    try:
        service.remove(repository_id)
    except RepositoryNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error


def _describe_git_failure(error: GitCommandError) -> str:
    """Reduce a git failure to the actionable line shown to the client."""

    message = error.stderr.strip()

    if not message:
        return "git command failed."

    # git reports the actionable cause on the last line of stderr.
    return message.splitlines()[-1].strip()
