# Evolutionary hotspot: how much, how recently and by how many people an
# event's code changed. An event's elements are one unit (owner, 2026-10-18).

import math
import re
import statistics
from collections import Counter
from collections.abc import Collection, Iterable, Sequence
from datetime import datetime
from itertools import pairwise
from pathlib import Path

import networkx as nx
import structlog

from app.components.degradation_scoring.features.errors import HistoryError
from app.components.degradation_scoring.features.history import (
    FileFilter,
    load_commits,
    map_to_elements,
)
from app.components.degradation_scoring.features.models import (
    ElementHistory,
    HotspotContext,
    HotspotFeatures,
)
from app.components.degradation_scoring.models import ResolvedEvent
from app.components.degradation_scoring.ports import CommitHistorySource, MiningCache

log = structlog.get_logger(__name__)

SECONDS_PER_DAY = 86_400

# A commit counts as a bug fix when its message has a fix word. Issue keys (#12, ABC-123)
# are not counted: GitHub squash merges and Apache-style repos put one on nearly every commit
# (C4-ADR-009). A heuristic and a declared threat to validity: "fix typo" counts, "resolve
# crash" does not.
FIX_WORDS = re.compile(
    r"\b(fix|fixed|fixes|fixing|bug|bugfix|defect|fault|patch|hotfix)\b", re.IGNORECASE
)


def is_bugfix(message: str) -> bool:
    return bool(FIX_WORDS.search(message))


def match_tag(release_id: str, tags: Collection[str]) -> str:
    # release id = git tag; "0.10.0" and "v0.10.0" are accepted for each other, logged
    if release_id in tags:
        return release_id
    other = release_id[1:] if release_id.startswith("v") else f"v{release_id}"
    if other in tags:
        log.info("release_tag_prefix", reason="tag_v_prefix", release=release_id, tag=other)
        return other
    raise HistoryError(f"release {release_id!r} has no git tag (also tried {other!r})")


def half_life_days(release_dates: Iterable[datetime], releases_per_half_life: float) -> float:
    # half-life = releases_per_half_life x median gap between consecutive releases, in days
    dates = sorted(release_dates)
    if len(dates) < 2:
        raise HistoryError("hotspot needs at least two dated releases for the decay half-life")
    gaps = [(b - a).total_seconds() / SECONDS_PER_DAY for a, b in pairwise(dates)]
    median = statistics.median(gaps)
    if median <= 0:
        raise HistoryError("releases share one date; the decay half-life is undefined")
    return releases_per_half_life * median


def hotspot_features(
    history: ElementHistory,
    members: Collection[str],
    *,
    release_date: datetime,
    decay_rate: float,
    cochange_threshold: int,
    max_files_per_commit: int,
) -> tuple[float, int, int, float, int]:
    # (churn_decayed, authors, coupling, bugfix_ratio, commits) of the unit "members":
    # churn = sum over commits of lines in the unit's files x exp(-rate x days before release),
    # each file once; coupling = outside elements co-changed in >= threshold commits, bulk
    # commits (> max_files_per_commit files) left out
    unit = set(members)
    touching = [c for c in history.commits if unit.intersection(c.lines_by_element)]
    churn = 0.0
    future = 0
    cochange: Counter[str] = Counter()
    for commit in touching:
        days = (release_date - commit.committed_at).total_seconds() / SECONDS_PER_DAY
        if days < 0:
            future += 1
        lines = sum(f.lines for f in commit.files if unit.intersection(f.elements))
        churn += lines * math.exp(-decay_rate * max(days, 0.0))
        if commit.files_changed <= max_files_per_commit:
            cochange.update(set(commit.lines_by_element) - unit)
    if future:
        log.info("commits_after_release", reason="commit_after_release", count=future)
    authors = len({c.author_email.lower() for c in touching})
    coupling = sum(1 for count in cochange.values() if count >= cochange_threshold)
    fixes = sum(1 for c in touching if is_bugfix(c.message))
    ratio = fixes / len(touching) if touching else 0.0
    return churn, authors, coupling, ratio, len(touching)


def compute_hotspots(
    events: Sequence[ResolvedEvent],
    graph: "nx.DiGraph[str]",
    *,
    source: CommitHistorySource | None,
    cache: MiningCache,
    repo_path: Path | None,
    file_filter: FileFilter,
    releases_per_half_life: float,
    cochange_threshold: int,
    max_files_per_commit: int,
) -> tuple[dict[str, HotspotFeatures], HotspotContext]:
    # hotspot features per event id plus the run context; inactive without a repository or
    # when no element has source paths. Range per event: first-seen (fallback start) -> end.
    inactive = HotspotContext(
        active=False,
        cochange_threshold=cochange_threshold,
        max_files_per_commit=max_files_per_commit,
    )
    if source is None or repo_path is None:
        log.info("hotspot_inactive", reason="no_repository")
        return {}, inactive.model_copy(update={"inactive_reason": "no_repository"})
    if not any(graph.nodes[node].get("source_paths") for node in graph):
        log.info("hotspot_inactive", reason="no_source_paths")
        return {}, inactive.model_copy(update={"inactive_reason": "no_source_paths"})

    tag_dates = {
        tag: datetime.fromisoformat(when) for tag, when in source.tag_dates(str(repo_path)).items()
    }
    # C3's release sequence: every release in the events' series, plus the detected release
    release_ids = {
        value.release_id
        for item in events
        for metric in item.event.affected_metrics
        for value in metric.series
    }
    release_ids |= {item.event.window.end_release for item in events}
    half_life = half_life_days(
        {tag_dates[match_tag(r, tag_dates)] for r in sorted(release_ids)}, releases_per_half_life
    )
    rate = math.log(2) / half_life

    histories: dict[tuple[str, str], ElementHistory] = {}
    features: dict[str, HotspotFeatures] = {}
    for item in events:
        first_seen = getattr(item.event, "first_seen_release", None)
        start = first_seen or item.event.window.start_release
        from_tag = match_tag(start, tag_dates)
        to_tag = match_tag(item.event.window.end_release, tag_dates)
        if (from_tag, to_tag) not in histories:
            commits = load_commits(
                source,
                cache,
                repo_path=repo_path,
                from_tag=from_tag,
                to_tag=to_tag,
                file_filter=file_filter,
            )
            histories[(from_tag, to_tag)] = map_to_elements(commits, graph)
        churn, authors, coupling, ratio, count = hotspot_features(
            histories[(from_tag, to_tag)],
            item.nodes,
            release_date=tag_dates[to_tag],
            decay_rate=rate,
            cochange_threshold=cochange_threshold,
            max_files_per_commit=max_files_per_commit,
        )
        features[item.event.event_id] = HotspotFeatures(
            churn_decayed=churn,
            authors=authors,
            coupling=coupling,
            bugfix_ratio=ratio,
            commits=count,
            from_release=from_tag,
            to_release=to_tag,
            first_seen_fallback=first_seen is None,
            paths_available=any(graph.nodes[n].get("source_paths") for n in item.nodes),
        )

    # the widest range (earliest start) contains every other one: report its unmapped share
    widest = min(histories, key=lambda key: tag_dates[key[0]])
    return features, inactive.model_copy(
        update={
            "active": True,
            "half_life_days": half_life,
            "decay_rate": rate,
            "unmapped_line_share": histories[widest].unmapped_line_share,
        }
    )
