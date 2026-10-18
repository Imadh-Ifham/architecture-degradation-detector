# Commit history for hotspot: file filter, cached-or-mined commits, files -> elements.
# Mining and caching go through ports; everything here is pure (CLAUDE.md §5.2, C4-ADR-001).

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

import networkx as nx
import pathspec
import structlog

from app.components.degradation_scoring.features.models import (
    CommitRecord,
    ElementCommit,
    ElementHistory,
)
from app.components.degradation_scoring.ports import CommitHistorySource, MiningCache

log = structlog.get_logger(__name__)

Spec = pathspec.PathSpec[Any]

# Bump when the meaning of mined rows changes, so old cache entries are not reused.
MINING_RULES_VERSION = "1:range=(from,to]:merges=excluded"


def _spec(patterns: Iterable[str]) -> Spec:
    return pathspec.PathSpec.from_lines("gitignore", patterns)


def split_globs(text: str) -> tuple[str, ...]:
    # "a, b,,c" -> ("a", "b", "c"); config.ini values are plain comma-separated strings
    return tuple(part.strip() for part in text.split(",") if part.strip())


@dataclass(frozen=True)
class FileFilter:
    # keeps a file if it matches an include glob and no exclude glob (gitignore syntax)

    include: tuple[str, ...]
    exclude: tuple[str, ...]

    @classmethod
    def from_settings(cls, include_globs: str, exclude_globs: str) -> "FileFilter":
        return cls(split_globs(include_globs), split_globs(exclude_globs))

    @cached_property
    def _include(self) -> Spec:
        return _spec(self.include)

    @cached_property
    def _exclude(self) -> Spec:
        return _spec(self.exclude)

    def keeps(self, path: str) -> bool:
        return self._include.match_file(path) and not self._exclude.match_file(path)

    @cached_property
    def fingerprint(self) -> str:
        # part of the cache key: other globs or rules mean a different cached result
        rules = {
            "version": MINING_RULES_VERSION,
            "include": sorted(self.include),
            "exclude": sorted(self.exclude),
        }
        canonical = json.dumps(rules, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def apply_filter(commit: CommitRecord, file_filter: FileFilter) -> CommitRecord | None:
    # drop filtered-out files; a commit with no file left is dropped as well
    kept = [change for change in commit.files if file_filter.keeps(change.path)]
    return commit.model_copy(update={"files": kept}) if kept else None


def load_commits(
    source: CommitHistorySource,
    cache: MiningCache,
    *,
    repo_path: Path,
    from_tag: str,
    to_tag: str,
    file_filter: FileFilter,
) -> list[CommitRecord]:
    # commits in (from_tag, to_tag] touching kept files; read from the cache when this range
    # was already mined with the same filter, otherwise mined and then cached
    key = (repo_path.resolve().as_posix(), from_tag, to_tag, file_filter.fingerprint)
    cached = cache.get(*key)
    if cached is not None:
        log.info("history_from_cache", reason="cache_hit", range=key[1:3], commits=len(cached))
        return [CommitRecord.model_validate(row) for row in cached]

    mined = (CommitRecord.model_validate(row) for row in source.commits(*key[:3]))
    commits = [kept for commit in mined if (kept := apply_filter(commit, file_filter))]
    cache.put(*key, [commit.model_dump(mode="json") for commit in commits])
    log.info("history_mined", reason="cache_miss", range=key[1:3], commits=len(commits))
    return commits


def map_to_elements(commits: Iterable[CommitRecord], graph: "nx.DiGraph[str]") -> ElementHistory:
    # a file belongs to every element whose source_paths match it (exact file, folder or glob);
    # files shared by several elements count for each and are reported, unmatched files too,
    # with the share of changed lines that no element owns
    specs: dict[str, Spec] = {}
    for node in sorted(graph):
        if paths := graph.nodes[node].get("source_paths"):
            specs[node] = _spec(paths)
    owners: dict[str, list[str]] = {}
    mapped: list[ElementCommit] = []
    total_lines = unmapped_lines = 0
    for commit in commits:
        lines: dict[str, int] = defaultdict(int)
        for change in commit.files:
            if change.path not in owners:
                owners[change.path] = [
                    n for n, spec in specs.items() if spec.match_file(change.path)
                ]
            changed = change.added + change.deleted
            total_lines += changed
            if not owners[change.path]:
                unmapped_lines += changed
            for node in owners[change.path]:
                lines[node] += changed
        if lines:
            mapped.append(
                ElementCommit(
                    hash=commit.hash,
                    author_email=commit.author_email,
                    committed_at=commit.committed_at,
                    message=commit.message,
                    files_changed=len(commit.files),
                    lines_by_element=dict(sorted(lines.items())),
                )
            )

    shared = sorted(path for path, nodes in owners.items() if len(nodes) > 1)
    unmapped = sorted(path for path, nodes in owners.items() if not nodes)
    if shared:
        log.info("files_shared_by_elements", reason="file_shared", count=len(shared))
    share = unmapped_lines / total_lines if total_lines else 0.0
    if unmapped:
        log.info(
            "files_without_element",
            reason="file_unmapped",
            count=len(unmapped),
            unmapped_line_share=round(share, 4),
        )
    return ElementHistory(
        commits=mapped,
        shared_files=shared,
        unmapped_files=unmapped,
        total_lines=total_lines,
        unmapped_lines=unmapped_lines,
        unmapped_line_share=share,
    )
