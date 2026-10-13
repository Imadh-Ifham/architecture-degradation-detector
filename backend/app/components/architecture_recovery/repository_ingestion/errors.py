"""Repository ingestion error hierarchy.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Defines the failure types the ingestion subcomponent can raise, so the API
    layer can map them onto HTTP status codes without knowing git details.
"""


class RepositoryIngestionError(Exception):
    """Base class for repository ingestion failures."""


class InvalidRepositorySource(RepositoryIngestionError):
    """The requested url or branch is not an acceptable repository source."""


class RepositoryNotFound(RepositoryIngestionError):
    """No ingested repository exists for the given identifier."""
