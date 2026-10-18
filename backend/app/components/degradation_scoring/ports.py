# Protocols for everything C4 needs from outside the component (INSTRUCTIONS §7.1).
# Implementations live under app/infrastructure/ or an entry point; tests use in-memory fakes.
# Each Protocol arrives with the first task that needs it. Still to come:
#   ArchitectureGraphSource (T09), CommitHistorySource + MiningCache (T12),
#   AdrIndexSource (T16), ScoringRunRepository (T20), TextGenerator + GenerationCache (T22),
#   TextEmbedder (T23), EntailmentJudge (T25), RefactoringDetector (T29).

from collections.abc import Sequence
from typing import Protocol


class DegradationEventSource(Protocol):
    def fetch(self, system_id: str, release_id: str) -> Sequence[object]:
        """Raw C3 event payloads for one (system, release), unvalidated (CLAUDE.md §4.1).

        Validation and quarantine happen in ingestion, so every source behaves the same.
        """
        ...
