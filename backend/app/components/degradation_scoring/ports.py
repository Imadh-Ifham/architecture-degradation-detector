# Protocols for everything C4 needs from outside the component (INSTRUCTIONS §7.1).
# Implementations live under app/infrastructure/ or an entry point; tests use in-memory fakes.
# Each Protocol arrives with the first task that needs it. Still to come:
#   CommitHistorySource + MiningCache (T12), AdrIndexSource (T16), ScoringRunRepository (T20),
#   TextGenerator + GenerationCache (T22), TextEmbedder (T23), EntailmentJudge (T25),
#   RefactoringDetector (T29).
# Sources return raw documents; ingestion validates them, so every source behaves the same.

from collections.abc import Sequence
from typing import Protocol


class DegradationEventSource(Protocol):
    # Raw C3 event payloads for one (system, release) (CLAUDE.md §4.1).
    def fetch(self, system_id: str, release_id: str) -> Sequence[object]: ...


class ArchitectureGraphSource(Protocol):
    # The raw graph document for one (system, release): C3's release package as a dict,
    # node-link JSON as a dict, or GraphML text (CLAUDE.md §4.3).
    def fetch(self, system_id: str, release_id: str) -> object: ...
