# Profile C4 hotspot mining on a real repository (C4-T14): one invocation = one run.
# Appends a row (runtime, commits, cache hit, unmapped share) to hotspot_runs_<name>.csv and
# writes the per-element hotspot table + a manifest to <C4>/docs/pp1/figures/.
# Usage, from backend/ (run twice to see the cache):
#     uv run python -m scripts.c4_hotspot_profile --from-tag v0.10.4 --to-tag v0.10.7

import argparse
import csv
import datetime as dt
import fnmatch
import json
import math
import subprocess
import time
from pathlib import Path
from typing import Any

import networkx as nx
import structlog
from sqlalchemy.orm import sessionmaker

from app.components.degradation_scoring.config import C4Config
from app.components.degradation_scoring.features.history import (
    FileFilter,
    load_commits,
    map_to_elements,
)
from app.components.degradation_scoring.features.hotspot import half_life_days, hotspot_features
from app.core.config import settings
from app.core.logging import configure_logging
from app.infrastructure.git.history import PyDrillerHistorySource
from app.infrastructure.postgres.database import engine
from app.infrastructure.postgres.repositories.mining_cache_repository import PostgresMiningCache

BACKEND_ROOT = Path(__file__).resolve().parents[1]
FIGURES = BACKEND_ROOT / "app" / "components" / "degradation_scoring" / "docs" / "pp1" / "figures"
DEFAULT_MAPPING = (
    BACKEND_ROOT
    / "tests/fixtures/degradation_scoring/mappings/online_boutique.source_paths.v1.json"
)
DEFAULT_REPO = settings.repositories_root / "c4-history" / "microservices-demo"

log = structlog.get_logger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--from-tag", required=True)
    parser.add_argument("--to-tag", required=True)
    parser.add_argument("--release-glob", default="v0.10.*", help="tags forming the releases")
    parser.add_argument("--name", default="online_boutique", help="name used in file names")
    parser.add_argument("--out", type=Path, default=FIGURES)
    return parser.parse_args()


def git_head(path: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def main() -> None:
    configure_logging()
    args = parse_args()
    config = C4Config.from_settings(settings)
    mapping: dict[str, Any] = json.loads(args.mapping.read_text(encoding="utf-8"))
    graph: nx.DiGraph[str] = nx.DiGraph()
    for element, paths in sorted(mapping["elements"].items()):
        graph.add_node(element, source_paths=paths)

    source = PyDrillerHistorySource()
    cache = PostgresMiningCache(sessionmaker(bind=engine))
    file_filter = FileFilter.from_settings(
        config.history_include_globs, config.history_exclude_globs
    )
    repo_key = args.repo.resolve().as_posix()

    started = time.perf_counter()
    tag_dates = {
        tag: dt.datetime.fromisoformat(when)
        for tag, when in source.tag_dates(str(args.repo)).items()
    }
    releases = sorted(
        (tag for tag in tag_dates if fnmatch.fnmatch(tag, args.release_glob)),
        key=tag_dates.__getitem__,
    )
    half_life = half_life_days([tag_dates[t] for t in releases], config.hotspot_half_life_releases)
    rate = math.log(2) / half_life
    cache_hit = cache.get(repo_key, args.from_tag, args.to_tag, file_filter.fingerprint) is not None
    mined_at = time.perf_counter()
    commits = load_commits(
        source,
        cache,
        repo_path=args.repo,
        from_tag=args.from_tag,
        to_tag=args.to_tag,
        file_filter=file_filter,
    )
    history_seconds = time.perf_counter() - mined_at
    history = map_to_elements(commits, graph)
    rows = []
    for element in sorted(graph):
        churn, authors, coupling, ratio, count = hotspot_features(
            history,
            [element],
            release_date=tag_dates[args.to_tag],
            decay_rate=rate,
            cochange_threshold=config.cochange_threshold,
            max_files_per_commit=config.max_files_per_commit,
        )
        rows.append(
            {
                "element": element,
                "churn_decayed": round(churn, 3),
                "authors": authors,
                "coupling": coupling,
                "bugfix_ratio": round(ratio, 4),
                "commits": count,
            }
        )
    total_seconds = time.perf_counter() - started

    args.out.mkdir(parents=True, exist_ok=True)
    features_path = args.out / f"hotspot_{args.name}.csv"
    previous = features_path.read_text(encoding="utf-8") if features_path.exists() else None
    with features_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    same_as_previous = previous == features_path.read_text(encoding="utf-8")

    runs_path = args.out / f"hotspot_runs_{args.name}.csv"
    run = {
        "run_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "window": f"({args.from_tag}, {args.to_tag}]",
        "cache": "hit" if cache_hit else "miss",
        "history_seconds": round(history_seconds, 3),
        "total_seconds": round(total_seconds, 3),
        "commits": len(commits),
        "mapped_commits": len(history.commits),
        "total_lines": history.total_lines,
        "unmapped_lines": history.unmapped_lines,
        "unmapped_line_share": round(history.unmapped_line_share, 4),
        "features_identical_to_previous_run": same_as_previous if previous else "",
    }
    new_file = not runs_path.exists()
    with runs_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(run))
        if new_file:
            writer.writeheader()
        writer.writerow(run)

    manifest = {
        "task": "C4-T14",
        "data_provenance": "live-history+manual-mapping",
        "mapping_file": args.mapping.relative_to(BACKEND_ROOT).as_posix(),
        "mapping_provenance": mapping["data_provenance"],
        "repository": mapping.get("repository"),
        "repository_head": git_head(args.repo),
        "code_commit": git_head(BACKEND_ROOT),
        "window": {"from_tag": args.from_tag, "to_tag": args.to_tag},
        "releases": releases,
        "half_life_days": half_life,
        "decay_rate_per_day": rate,
        "cochange_threshold": config.cochange_threshold,
        "max_files_per_commit": config.max_files_per_commit,
        "filter_hash": file_filter.fingerprint,
        "include_globs": list(file_filter.include),
        "exclude_globs": list(file_filter.exclude),
        "shared_files": history.shared_files,
        "unmapped_files": history.unmapped_files,
    }
    (args.out / f"hotspot_{args.name}.manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(run, indent=2))


if __name__ == "__main__":
    main()
