"""Decision records kept in a repository of their own.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    Teams that do write decisions down often keep them away from the code, in
    a repository the architects own. The parser is the same one; the
    repository is not.

    The workspace is prepared before this runs. Cloning a repository at a
    branch is solved, tested and merged in the ingestion service, so the API
    calls it a second time and hands this source the resulting workspace -
    which also means the decision repository gets the same credential
    handling, timeout and cleanup the code repository already gets.

    When no decision repository was named, this reports that it did not run.
    Returning an empty result instead would make "the architects keep no
    decisions" and "nobody told us where they are" the same answer.
"""

from ...ports import SourceArtifactReader
from .base import SourceOutcome, SourceRequest, collect_decision_documents


class ExternalDecisionRecords:
    """Decision records kept in a separate repository the user names."""

    name = "external_adr"

    def __init__(self, reader: SourceArtifactReader) -> None:
        self._reader = reader

    def collect(self, request: SourceRequest) -> SourceOutcome:
        """Read every decision record the named repository holds."""

        if not request.adr_repository_id:
            return SourceOutcome(
                source=self.name, ran=False, reason="no decision repository was named"
            )

        records = collect_decision_documents(
            self._reader, request.adr_repository_id, request, self.name
        )

        return SourceOutcome(
            source=self.name,
            ran=True,
            records=records,
            reason=None if records else "no decision records in that repository",
        )


__all__ = ["ExternalDecisionRecords"]
