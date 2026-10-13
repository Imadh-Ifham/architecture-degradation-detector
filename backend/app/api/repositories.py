"""Repository ingestion endpoints.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Exposes the repository ingestion subcomponent over HTTP: clone a
    repository onto the machine, list what is present, and remove it again.

    A successful clone is followed immediately by a repository inventory, and
    the summary is included in the response. The two subcomponents stay
    independent: this transport layer is the only place that knows the
    inventory runs after an ingestion.
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
from app.components.architecture_recovery.repository_inventory import (
    RepositoryInventoryError,
    RepositoryInventoryService,
    RepositoryInventorySummaryResponse,
    inventory_options_from_settings,
)
from app.core.config import settings
from app.domain.repository import IngestedRepository
from app.infrastructure.git.client import GitClient, GitCommandError


router = APIRouter(prefix="/repositories", tags=["Repositories"])


class RepositoryIngestionResponse(IngestedRepositoryResponse):
    """An ingested repository plus the inventory taken from the fresh clone.

    `inventory` is null when the inventory could not be produced, in which case
    `inventory_error` explains why. The clone itself is unaffected either way.
    """

    inventory: RepositoryInventorySummaryResponse | None = None
    inventory_error: str | None = None


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


@lru_cache
def get_repository_inventory_service() -> RepositoryInventoryService:
    """Provide the inventory service shared by all requests.

    Cached so the scan limits are read once. Declared as a FastAPI dependency
    so tests can override it.
    """

    return RepositoryInventoryService(options=inventory_options_from_settings())


@router.post(
    "",
    response_model=RepositoryIngestionResponse,
    status_code=status.HTTP_201_CREATED,
)
def ingest_repository(
    request: RepositoryIngestionRequest,
    service: RepositoryIngestionService = Depends(get_repository_ingestion_service),
    inventory_service: RepositoryInventoryService = Depends(
        get_repository_inventory_service
    ),
) -> RepositoryIngestionResponse:
    """Clone `request.url` at `request.branch`, then inventory the clone."""

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

    # The clone has succeeded, so from here on nothing may report the ingest as
    # failed: an inventory problem is surfaced in the body instead.
    inventory, inventory_error = _inventory_after_ingest(repository, inventory_service)

    return RepositoryIngestionResponse(
        **IngestedRepositoryResponse.model_validate(repository).model_dump(),
        inventory=inventory,
        inventory_error=inventory_error,
    )


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


def _inventory_after_ingest(
    repository: IngestedRepository,
    inventory_service: RepositoryInventoryService,
) -> tuple[RepositoryInventorySummaryResponse | None, str | None]:
    """Inventory a freshly cloned working tree.

    Returns the summary and an error message, exactly one of which is set.
    Only `RepositoryInventoryError` is caught: that covers the expected
    failures (an unwritable output directory, a missing working tree). An
    unexpected exception is a defect and is deliberately allowed to surface.
    """

    try:
        path, inventory = inventory_service.run_for_ingested(repository)
    except RepositoryInventoryError as error:
        return None, str(error)

    return RepositoryInventorySummaryResponse.from_inventory(path, inventory), None


def _describe_git_failure(error: GitCommandError) -> str:
    """Reduce a git failure to the actionable line shown to the client."""

    message = error.stderr.strip()

    if not message:
        return "git command failed."

    # git reports the actionable cause on the last line of stderr.
    return message.splitlines()[-1].strip()
