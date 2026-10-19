"""Repository ingestion HTTP schemas.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Request and response bodies of the repository ingestion endpoints. Field
    level rules here only enforce shape; the semantic url and revision rules
    live in `validation.py`.
"""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class RepositoryIngestionRequest(BaseModel):
    """Body of `POST /repositories`."""

    url: str = Field(min_length=1, max_length=2048)
    branch: str = Field(min_length=1, max_length=255)


class RepositoryReleaseRequest(BaseModel):
    """Body of `POST /repositories/releases`.

    `revision` is a tag or a commit SHA. It is resolved to a commit before
    anything is stored, so a tag that later moves does not change what this
    request analyzed.
    """

    url: str = Field(min_length=1, max_length=2048)
    revision: str = Field(min_length=1, max_length=255)
    branch: str | None = Field(default=None, max_length=255)


class IngestedRepositoryResponse(BaseModel):
    """Single ingested repository returned to the client."""

    # Lets the model be built straight from the domain dataclass.
    model_config = ConfigDict(from_attributes=True)

    id: str
    url: str
    branch: str
    commit: str
    path: Path
    ingested_at: datetime
    repository_id: str | None = None
    release_tag: str | None = None
    revision: str | None = None
    release_date: datetime | None = None
    release_date_source: str | None = None
    commit_date: datetime | None = None
