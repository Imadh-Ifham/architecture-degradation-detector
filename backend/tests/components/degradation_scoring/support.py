# Shared test helpers for C4: default config, fixture loading and in-memory port fakes.

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import git

from app.components.degradation_scoring.config import C4Config
from app.components.degradation_scoring.reporting.models import EventNotes, ReportView
from app.core.config import Settings
from app.domain.degradation_event import ContextTag, ReviewStatus, Scope
from app.domain.severity_report import (
    DataProvenance,
    Dimension,
    DimensionScore,
    NormalizationMode,
    QuarantinedEvent,
    QuarantineReason,
    Resolution,
    ResolutionStatus,
    SeverityRecord,
    SeverityReportV1,
    SkippedEvent,
    SkipReason,
    WeightsProvenance,
)

Rows = list[Mapping[str, object]]

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "degradation_scoring"


def default_config(**overrides: Any) -> C4Config:
    # C4Config from the declared defaults only, so a developer's .env cannot change a test.
    settings = Settings.model_construct(
        postgres_host="localhost",
        postgres_db="db",
        postgres_user="user",
        postgres_password="password",
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="password",
    )
    return C4Config.from_settings(settings).model_copy(update=overrides)


def load_fixture(relative: str) -> Any:
    return json.loads((FIXTURES / relative).read_text(encoding="utf-8"))


class FakeEventSource:
    # DegradationEventSource over in-memory payloads; records what was asked for.

    def __init__(self, payloads: Sequence[object]) -> None:
        self._payloads = list(payloads)
        self.requests: list[tuple[str, str]] = []

    def fetch(self, system_id: str, release_id: str) -> Sequence[object]:
        self.requests.append((system_id, release_id))
        return list(self._payloads)


class FakeGraphSource:
    # ArchitectureGraphSource over in-memory documents keyed by release; records requests.

    def __init__(self, documents: dict[str, object]) -> None:
        self._documents = documents
        self.requests: list[tuple[str, str]] = []

    def fetch(self, system_id: str, release_id: str) -> object:
        self.requests.append((system_id, release_id))
        return self._documents[release_id]


class FakeHistorySource:
    # CommitHistorySource over in-memory rows; records every call.

    def __init__(self, rows: Sequence[Mapping[str, object]]) -> None:
        self._rows = list(rows)
        self.requests: list[tuple[str, str, str]] = []

    def commits(self, repo_path: str, from_tag: str, to_tag: str) -> Sequence[Mapping[str, object]]:
        self.requests.append((repo_path, from_tag, to_tag))
        return list(self._rows)

    def tag_dates(self, repo_path: str) -> Mapping[str, str]:
        return {}


class FakeMiningCache:
    # MiningCache in a dict, keyed like the Postgres table.

    def __init__(self) -> None:
        self.entries: dict[tuple[str, str, str, str], list[Mapping[str, object]]] = {}

    def get(
        self, repo_path: str, from_tag: str, to_tag: str, filter_hash: str
    ) -> Sequence[Mapping[str, object]] | None:
        return self.entries.get((repo_path, from_tag, to_tag, filter_hash))

    def put(
        self,
        repo_path: str,
        from_tag: str,
        to_tag: str,
        filter_hash: str,
        rows: Sequence[Mapping[str, object]],
    ) -> None:
        self.entries[(repo_path, from_tag, to_tag, filter_hash)] = list(rows)


def _lines(count: int, prefix: str = "line") -> str:
    return "".join(f"{prefix} {i}\n" for i in range(count))


ORDER = "src/order/OrderService.java"
PAY = "src/pay/PayService.java"
UTIL = "src/shared/Util.java"


def init_repo(root: Path) -> git.Repo:
    # empty repo on "main" with line endings and signing pinned, so tests run the same anywhere
    repo = git.Repo.init(root, initial_branch="main")
    with repo.config_writer() as config:
        config.set_value("core", "autocrlf", "false")
        config.set_value("commit", "gpgsign", "false")
    return repo


def git_commit(
    repo: git.Repo,
    day: int,
    email: str,
    message: str,
    files: dict[str, str | None],
    *,
    merge: str | None = None,
) -> str:
    # writes (None = deletes) the files, then commits on 2026-01-<day> 12:00 UTC as email;
    # with merge="branch" it makes a --no-ff merge commit instead; returns the new hash
    root = Path(repo.working_dir)
    for name, content in files.items():
        if content is None:
            repo.git.rm(name)
            continue
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        repo.git.add(name)
    when = f"2026-01-{day:02d}T12:00:00+00:00"
    user = email.split("@")[0]
    with repo.git.custom_environment(
        GIT_AUTHOR_NAME=user,
        GIT_AUTHOR_EMAIL=email,
        GIT_AUTHOR_DATE=when,
        GIT_COMMITTER_NAME=user,
        GIT_COMMITTER_EMAIL=email,
        GIT_COMMITTER_DATE=when,
    ):
        if merge:
            repo.git.merge(merge, no_ff=True, m=message)
        else:
            repo.git.commit(m=message)
    return repo.head.commit.hexsha


def build_tiny_repo(root: Path) -> dict[str, str]:
    # A small history with fixed dates; returns commit hashes by label.
    # v1.0.0 = c0; then c2 (feature branch), c1, merge, c3, c4, c5 = v1.1.0; c6 after the tag.
    # .mailmap (c0) maps bob.work@ (c5) to bob@.
    repo = init_repo(root)
    hashes: dict[str, str] = {}

    def commit(
        label: str, day: int, email: str, message: str, files: dict[str, str | None]
    ) -> None:
        merge = "feature" if label == "merge" else None
        hashes[label] = git_commit(repo, day, email, message, files, merge=merge)

    order_v2 = "changed\n" + _lines(10).split("\n", 1)[1] + _lines(3, "total")
    commit(
        "c0",
        1,
        "alice@example.com",
        "initial",
        {
            ORDER: _lines(10),
            PAY: _lines(5),
            UTIL: _lines(2),
            "README.md": "readme\n",
            ".mailmap": "Bob <bob@example.com> <bob.work@example.com>\n",
        },
    )
    repo.create_tag("v1.0.0")
    repo.git.checkout("-b", "feature")
    commit("c2", 3, "bob@example.com", "pay: add retry", {PAY: _lines(5) + _lines(2, "retry")})
    repo.git.checkout("main")
    commit(
        "c1",
        5,
        "Alice@Example.com",
        "order: rework totals",
        {
            ORDER: order_v2,
            "vendor/lib/Dep.java": _lines(3),
            "target/Out.java": _lines(3),
            "src/cartservice/bin/Cart.cs": _lines(3),
        },
    )
    commit("merge", 6, "alice@example.com", "merge feature", {})
    commit(
        "c3",
        8,
        "alice@example.com",
        "fix: null check in util",
        {UTIL: _lines(2) + _lines(4, "check"), ORDER: order_v2 + "guard\n"},
    )
    commit(
        "c4",
        9,
        "bob@example.com",
        "docs",
        {"README.md": "readme v2\n", "vendor/lib/Dep.java": None},
    )
    commit(
        "c5", 10, "bob.work@example.com", "search: new module", {"src/search/Search.py": _lines(3)}
    )
    repo.create_tag("v1.1.0")
    commit("c6", 12, "bob@example.com", "after release", {ORDER: _lines(1)})
    repo.close()
    return hashes


def adr_index_document() -> dict[str, Any]:
    # the three fixture ADRs ("0001-x.md" -> "ADR-0001") plus the fixture links (stand-in for
    # C2's adr_refs), in the AdrIndexSource document shape
    adrs = [
        {"id": f"ADR-{path.name[:4]}", "text": path.read_text(encoding="utf-8")}
        for path in sorted((FIXTURES / "adr").glob("*.md"))
    ]
    return {"adrs": adrs, "links": load_fixture("adr/adr_links.v1.json")["links"]}


class FakeRunRepository:
    # ScoringRunRepository in memory; keeps every saved run's rows.

    def __init__(self) -> None:
        self.saved: list[tuple[Mapping[str, object], Rows, Rows, Rows]] = []

    def save(
        self,
        run: Mapping[str, object],
        ingestion: Sequence[Mapping[str, object]],
        features: Sequence[Mapping[str, object]],
        scores: Sequence[Mapping[str, object]],
    ) -> None:
        self.saved.append((run, list(ingestion), list(features), list(scores)))


def sample_report(**overrides: Any) -> SeverityReportV1:
    # a small valid report by hand: two ranked events (BR + PS on, EH + AV off), one
    # quarantined and one skipped
    def record(event_id: str, rank: int, severity: float, br: float) -> SeverityRecord:
        def score(value: float, weight: float) -> DimensionScore:
            return DimensionScore(raw=value, normalized=value, weight=weight)

        off = DimensionScore(raw=0.0, normalized=0.0, weight=0.0, active=False)
        return SeverityRecord(
            event_id=event_id,
            anti_pattern_type="CyclicDependency",
            scope=Scope.INSTANCE,
            review_status=ReviewStatus.PENDING,
            context_tag=ContextTag.GENUINE,
            rank=rank,
            severity=severity,
            dimensions={
                Dimension.BLAST_RADIUS: score(br, 0.75),
                Dimension.HOTSPOT: off,
                Dimension.ADR_VIOLATION: off,
                Dimension.PERSISTENCE: score(0.5, 0.25),
            },
            contributions={
                Dimension.BLAST_RADIUS: 0.8,
                Dimension.HOTSPOT: 0.0,
                Dimension.ADR_VIOLATION: 0.0,
                Dimension.PERSISTENCE: 0.2,
            },
            resolution=Resolution(status=ResolutionStatus.EXACT, confidence=1.0),
        )

    values: dict[str, Any] = {
        "run_id": "unit-run",
        "system_id": "unit-system",
        "release_id": "v1.0.0",
        "data_provenance": DataProvenance.FIXTURE,
        "active_dimensions": [Dimension.BLAST_RADIUS, Dimension.PERSISTENCE],
        "weights_version": "ahp_v1",
        "weights_provenance": WeightsProvenance.PROVISIONAL_AUTHOR_ELICITED,
        "ahp_cr": 0.0114,
        "normalization": NormalizationMode.MINMAX_SMALL_N,
        "resolution_rate": 0.5,
        "records": [record("E-1", 1, 0.7, 0.9), record("E-2", 2, 0.4, 0.3)],
        "quarantined": [
            QuarantinedEvent(
                event_id="E-3", reason=QuarantineReason.UNRESOLVED_ELEMENT, detail="missing: x"
            )
        ],
        "skipped": [SkippedEvent(event_id="E-4", reason=SkipReason.INTENTIONAL)],
    }
    return SeverityReportV1(**(values | overrides))


def sample_view(**overrides: Any) -> ReportView:
    # the HTML extras matching sample_report()
    values: dict[str, Any] = {
        "payloads": 4,
        "topsis_mode": "fixed_reference",
        "weights_elicited_by": "Tester",
        "ahp_lambda_max": 4.031,
        "elicited_weights": {
            Dimension.BLAST_RADIUS: 0.45,
            Dimension.HOTSPOT: 0.3,
            Dimension.ADR_VIOLATION: 0.1,
            Dimension.PERSISTENCE: 0.15,
        },
        "weights": {
            Dimension.BLAST_RADIUS: 0.75,
            Dimension.HOTSPOT: 0.0,
            Dimension.ADR_VIOLATION: 0.0,
            Dimension.PERSISTENCE: 0.25,
        },
        "hotspot_inactive_reason": "no_repository",
        "adr_inactive_reason": "no_adr_index",
        "notes": {
            "E-1": EventNotes(nodes=["a", "b"], flags=["fallback: presence", "hotspot off"]),
            "E-2": EventNotes(nodes=["c"], flags=["ADR off"], growth_metric="fan_in"),
        },
    }
    return ReportView(**(values | overrides))
