# Tests for the hotspot features (C4-T13, FR-05), hand-computed on a small git repo.
# Releases v1..v4 on days 1, 8, 15, 29: gaps 7, 7, 14 -> median 7 -> half-life 2 x 7 = 14 days.

import copy
import datetime as dt
import math
from pathlib import Path
from typing import Any

import networkx as nx
import pytest
from structlog.testing import capture_logs

from app.components.degradation_scoring.features.errors import HistoryError
from app.components.degradation_scoring.features.hotspot import (
    half_life_days,
    hotspot_features,
    is_bugfix,
    match_tag,
)
from app.components.degradation_scoring.features.models import (
    ElementCommit,
    ElementHistory,
    MappedFile,
)
from app.components.degradation_scoring.features.service import FeatureExtractionService
from app.components.degradation_scoring.models import ResolvedEvent
from app.domain.degradation_event import DegradationEventV2, SeriesValue
from app.domain.severity_report import Resolution, ResolutionStatus
from app.infrastructure.git.history import PyDrillerHistorySource
from tests.components.degradation_scoring.support import (
    default_config,
    git_commit,
    init_repo,
    load_fixture,
)

RATE = math.log(2) / 14  # lambda per day
ORDER = "src/order/Order.java"
PAY = "src/pay/Pay.java"
UTIL = "src/shared/Util.java"
SEARCH = "src/search/Search.py"  # owned by no element


def lines(count: int, prefix: str = "line") -> str:
    return "".join(f"{prefix} {i}\n" for i in range(count))


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("hotspot-repo")
    repo = init_repo(root)
    alice, bob = "alice@example.com", "Bob@Example.com"
    git_commit(
        repo,
        1,
        alice,
        "initial",
        {ORDER: lines(10), PAY: lines(5), UTIL: lines(2), SEARCH: lines(1)},
    )
    repo.create_tag("v1")
    git_commit(repo, 8, alice, "search: more", {SEARCH: lines(2)})
    repo.create_tag("v2")
    git_commit(repo, 15, alice, "search: even more", {SEARCH: lines(3)})
    repo.create_tag("v3")
    # (v3, v4]: day 22 order +3 and pay +1; day 25 shared util +4; day 29 order +2 (= v4)
    git_commit(
        repo,
        22,
        alice,
        "fix: rounding",
        {ORDER: lines(10) + lines(3, "round"), PAY: lines(5) + "retry\n"},
    )
    git_commit(repo, 25, bob, "feature: util", {UTIL: lines(2) + lines(4, "util")})
    git_commit(
        repo, 29, alice, "ABC-12 tidy", {ORDER: lines(10) + lines(3, "round") + lines(2, "tidy")}
    )
    repo.create_tag("v4")
    repo.close()
    return root


def graph() -> "nx.DiGraph[str]":
    g: nx.DiGraph[str] = nx.DiGraph()
    g.add_node("order", source_paths=["src/order/**", "src/shared/**"])
    g.add_node("pay", source_paths=["src/pay/**", "src/shared/**"])
    g.add_node("ui", source_paths=[])
    g.add_edge("ui", "order", weight=1)
    return g


PAYLOAD: dict[str, Any] = load_fixture("events/fixture_events.v1.json")[2]


def event(
    event_id: str,
    nodes: list[str],
    *,
    start: str = "v3",
    end: str = "v4",
    series: tuple[str, ...] = ("v1", "v2", "v3", "v4"),
) -> ResolvedEvent:
    base = DegradationEventV2.model_validate(copy.deepcopy(PAYLOAD))
    metric = base.affected_metrics[0].model_copy(
        update={"series": [SeriesValue(release_id=r, value=1.0) for r in series]}
    )
    window = base.window.model_copy(update={"start_release": start, "end_release": end})
    return ResolvedEvent(
        event=base.model_copy(
            update={"event_id": event_id, "window": window, "affected_metrics": [metric]}
        ),
        nodes=nodes,
        resolution=Resolution(status=ResolutionStatus.EXACT, confidence=1.0),
    )


def extract(repo_path: Path | None, *events: ResolvedEvent, **overrides: Any) -> Any:
    service = FeatureExtractionService(default_config(**overrides), PyDrillerHistorySource())
    return service.extract(list(events), graph(), repo_path)


def test_order_features_by_hand(repo: Path) -> None:
    result = extract(repo, event("E-order", ["order"]))
    order = result.events[0].hotspot

    # order's lines: 3 on day 22, 4 (shared util) on day 25, 2 on day 29 (= release day)
    churn = 3 * math.exp(-RATE * 7) + 4 * math.exp(-RATE * 4) + 2
    assert order.churn_decayed == pytest.approx(churn, abs=1e-9)
    assert order.churn_decayed == pytest.approx(3 * 2**-0.5 + 4 * 2 ** (-2 / 7) + 2, abs=1e-9)
    assert order.authors == 2  # alice, bob (any case)
    assert order.coupling == 0  # pay co-changes in 2 commits < theta 5
    assert order.bugfix_ratio == pytest.approx(2 / 3)  # "fix: rounding", "ABC-12 tidy"
    assert order.commits == 3
    assert (order.from_release, order.to_release) == ("v3", "v4")
    assert order.first_seen_fallback  # C3 does not send first_seen_release yet
    assert order.paths_available


def test_run_metadata_records_lambda_half_life_and_theta(repo: Path) -> None:
    context = extract(repo, event("E-order", ["order"])).hotspot

    assert context.active
    assert context.half_life_days == pytest.approx(14.0)
    assert context.decay_rate == pytest.approx(RATE)
    assert (context.cochange_threshold, context.max_files_per_commit) == (5, 50)


def test_a_two_element_event_counts_a_shared_file_once(repo: Path) -> None:
    unit = extract(repo, event("E-both", ["order", "pay"])).events[0].hotspot

    # day 22: order 3 + pay 1; day 25: util 4 once (not 4 + 4); day 29: order 2
    churn = 4 * math.exp(-RATE * 7) + 4 * math.exp(-RATE * 4) + 2
    assert unit.churn_decayed == pytest.approx(churn, abs=1e-9)
    assert unit.coupling == 0  # nothing outside the unit changes with it
    assert (unit.authors, unit.commits) == (2, 3)


def test_coupling_counts_outside_elements_above_theta(repo: Path) -> None:
    order = extract(repo, event("E", ["order"]), cochange_threshold=2).events[0].hotspot

    assert order.coupling == 1  # pay co-changed on day 22 and day 25


def test_bulk_commits_are_left_out_of_coupling_only(repo: Path) -> None:
    order = (
        extract(repo, event("E", ["order"]), cochange_threshold=2, max_files_per_commit=1)
        .events[0]
        .hotspot
    )

    # day 22 touches 2 files: too many for co-change, still counted for churn and commits
    assert order.coupling == 0
    assert order.commits == 3


def test_element_without_paths_is_flagged(repo: Path) -> None:
    ui = extract(repo, event("E-ui", ["ui"])).events[0].hotspot

    assert not ui.paths_available
    assert (ui.commits, ui.churn_decayed, ui.bugfix_ratio) == (0, 0.0, 0.0)


def test_unmapped_share_comes_from_the_widest_range(repo: Path) -> None:
    context = extract(repo, event("A", ["order"]), event("B", ["pay"], start="v2")).hotspot

    # (v2, v4]: search +1 (unowned) on day 15, then 4 + 4 + 2 owned lines -> 1 / 11
    assert context.unmapped_line_share == pytest.approx(1 / 11)


def test_release_ids_without_v_find_their_tags(repo: Path) -> None:
    with capture_logs() as logs:
        result = extract(
            repo, event("E", ["order"], start="3", end="4", series=("1", "2", "3", "4"))
        )

    assert result.events[0].hotspot.from_release == "v3"
    assert "tag_v_prefix" in {entry["reason"] for entry in logs}


def test_missing_tag_stops_the_run(repo: Path) -> None:
    with pytest.raises(HistoryError, match="'v9' has no git tag"):
        extract(repo, event("E", ["order"], end="v9", series=("v1", "v9")))


def test_graph_without_paths_makes_hotspot_inactive(repo: Path) -> None:
    g: nx.DiGraph[str] = nx.DiGraph()
    g.add_node("order")
    service = FeatureExtractionService(default_config(), PyDrillerHistorySource())

    result = service.extract([event("E", ["order"])], g, repo)

    assert result.events[0].hotspot is None
    assert result.hotspot.inactive_reason == "no_source_paths"


def test_service_without_history_source_is_inactive(repo: Path) -> None:
    result = FeatureExtractionService(default_config()).extract(
        [event("E", ["order"])], graph(), repo
    )

    assert result.hotspot.inactive_reason == "no_repository"


# Pure helpers


@pytest.mark.parametrize(
    "message",
    [
        "fix: null check",
        "Fixed login crash",
        "fixes the totals",
        "Fixing flaky test",
        "bugfix: rounding",
        "hotfix for prod",
        "Patch the parser",
        "ABC-123 tidy",
        "closes #45",
    ],
)
def test_bugfix_messages(message: str) -> None:
    assert is_bugfix(message)


@pytest.mark.parametrize(
    "message",
    ["prefix handling", "debugging output", "abc-123 tidy", "resolve crash", "add feature"],
)
def test_not_bugfix_messages(message: str) -> None:
    # "resolve crash" is a real fix the heuristic misses: a declared threat to validity
    assert not is_bugfix(message)


def test_match_tag() -> None:
    tags = {"v1.0.0", "2.0.0"}

    assert match_tag("v1.0.0", tags) == "v1.0.0"
    assert match_tag("1.0.0", tags) == "v1.0.0"
    assert match_tag("v2.0.0", tags) == "2.0.0"
    with pytest.raises(HistoryError, match=r"'3.0.0' has no git tag \(also tried 'v3.0.0'\)"):
        match_tag("3.0.0", tags)


def day(n: int) -> dt.datetime:
    return dt.datetime(2026, 1, n, 12, tzinfo=dt.UTC)


def test_half_life_is_twice_the_median_gap() -> None:
    assert half_life_days([day(29), day(1), day(15), day(8)], 2.0) == pytest.approx(14.0)
    assert half_life_days([day(1), day(3)], 2.0) == pytest.approx(4.0)


def test_half_life_needs_two_distinct_dates() -> None:
    with pytest.raises(HistoryError, match="at least two"):
        half_life_days([day(1)], 2.0)
    with pytest.raises(HistoryError, match="one date"):
        half_life_days([day(1), day(1), day(1)], 2.0)


def commit_at(when: dt.datetime, lines_: int = 5) -> ElementCommit:
    return ElementCommit(
        hash="h",
        author_email="a@example.com",
        committed_at=when,
        message="m",
        files_changed=1,
        lines_by_element={"x": lines_},
        files=[MappedFile(path="x.py", lines=lines_, elements=["x"])],
    )


def test_commit_after_the_release_counts_in_full_and_is_logged() -> None:
    history = ElementHistory(commits=[commit_at(day(20))])

    with capture_logs() as logs:
        churn, *_ = hotspot_features(
            history,
            ["x"],
            release_date=day(10),
            decay_rate=RATE,
            cochange_threshold=5,
            max_files_per_commit=50,
        )

    assert churn == 5.0
    assert [entry["reason"] for entry in logs] == ["commit_after_release"]


def test_half_life_old_commit_counts_half() -> None:
    history = ElementHistory(commits=[commit_at(day(1), 8)])

    churn, *_ = hotspot_features(
        history,
        ["x"],
        release_date=day(15),
        decay_rate=math.log(2) / 14,
        cochange_threshold=5,
        max_files_per_commit=50,
    )

    assert churn == pytest.approx(4.0)
