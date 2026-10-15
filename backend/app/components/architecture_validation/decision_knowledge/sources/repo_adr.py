"""Decision records written in the code repository.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    The source the research assumed would be the only one, and the one that
    finds nothing on most repositories.

    It has to run anyway, and it has to be seen to run. "This repository keeps
    no decision records" is the empirical result the rest of the design rests
    on, and an adapter that was skipped establishes nothing at all. That is
    what the outcome's `ran` flag is for: zero records from a source that ran
    is a finding about the repository, and zero from a source that did not is
    a fact about the configuration.
"""

from ...ports import SourceArtifactReader
from .base import SourceOutcome, SourceRequest, collect_decision_documents


class RepositoryDecisionRecords:
    """Decision records kept beside the code they describe."""

    name = "repo_adr"

    def __init__(self, reader: SourceArtifactReader) -> None:
        self._reader = reader

    def collect(self, request: SourceRequest) -> SourceOutcome:
        """Read every decision record the code repository holds."""

        records = collect_decision_documents(
            self._reader, request.code_repository_id, request, self.name
        )

        return SourceOutcome(
            source=self.name,
            ran=True,
            records=records,
            reason=None if records else "no decision records in this repository",
        )


__all__ = ["RepositoryDecisionRecords"]
