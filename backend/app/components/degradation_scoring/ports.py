# Protocols for everything C4 needs from outside the component (INSTRUCTIONS §7.1).
# Implementations live under app/infrastructure/ or an entry point; tests use in-memory fakes.
# Each Protocol arrives with the first task that needs it. Still to come:
#   TextGenerator + GenerationCache (T22),
#   TextEmbedder (T23), EntailmentJudge (T25), RefactoringDetector (T29).
# Sources return raw documents; C4 validates them, so every source behaves the same.

from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class DegradationEventSource(Protocol):
    # Raw C3 event payloads for one (system, release) (CLAUDE.md §4.1).
    def fetch(self, system_id: str, release_id: str) -> Sequence[object]: ...


class ArchitectureGraphSource(Protocol):
    # The raw graph document for one (system, release): C3's release package as a dict,
    # node-link JSON as a dict, or GraphML text (CLAUDE.md §4.3).
    def fetch(self, system_id: str, release_id: str) -> object: ...


class CommitHistorySource(Protocol):
    # Plain commit rows in (from_tag, to_tag], merge commits left out, author e-mails after
    # .mailmap (CLAUDE.md §5.2): {"hash", "author_email", "committed_at" (ISO 8601),
    # "message", "files": [{"path" (posix), "added", "deleted"}]}
    def commits(
        self, repo_path: str, from_tag: str, to_tag: str
    ) -> Sequence[Mapping[str, object]]: ...

    # Every tag with the date (ISO 8601) of the commit it points to.
    def tag_dates(self, repo_path: str) -> Mapping[str, str]: ...


class MiningCache(Protocol):
    # Filtered commit rows per mined range; get() returns None when the range is not cached.
    def get(
        self, repo_path: str, from_tag: str, to_tag: str, filter_hash: str
    ) -> Sequence[Mapping[str, object]] | None: ...

    def put(
        self,
        repo_path: str,
        from_tag: str,
        to_tag: str,
        filter_hash: str,
        rows: Sequence[Mapping[str, object]],
    ) -> None: ...


class AdrIndexSource(Protocol):
    # The raw ADR index of one (system, release), or None when there is none (AV inactive):
    # {"adrs": [{"id", "text" (markdown)}], "links": {element_id: [adr_id]}}, links = C2's
    # adr_refs (CLAUDE.md §5.3)
    def fetch(self, system_id: str, release_id: str) -> object | None: ...


class ScoringRunRepository(Protocol):
    # Saves one run for inspection (C4-T16b, CLAUDE.md §6) as plain rows (infrastructure may
    # not import components): the run, one row per input payload, one features row and one
    # scores row per ranked event. Column names = the c4_scoring_run / c4_event_ingestion /
    # c4_event_features / c4_event_scores columns.
    def save(
        self,
        run: Mapping[str, object],
        ingestion: Sequence[Mapping[str, object]],
        features: Sequence[Mapping[str, object]],
        scores: Sequence[Mapping[str, object]],
    ) -> None: ...


class SavedReportSource(Protocol):
    # Reports already written by rank() (CLAUDE.md §6), for the read API: runs() = every run's
    # c4_run_manifest.json document; reports(run_id) = the c4_report.json document of every run
    # folder with that id (more than one only if two systems reuse an id).
    def runs(self) -> Sequence[Mapping[str, object]]: ...

    def reports(self, run_id: str) -> Sequence[Mapping[str, object]]: ...


class DetectionHandoverSource(Protocol):
    # What degradation detection (C3) leaves for scoring after a run: {"events": [...],
    # "package": {...}} = its events.json and the release package of the window's last
    # release; None when that run left no hand-over.
    def read(self, system_id: str, detection_run_id: str) -> Mapping[str, Any] | None: ...
