# Rank one release's degradation events and write the report, HTML and run manifest (C4-T20)
# under <SCORING_OUTPUTS_ROOT>/<system>/<run_id>/. Usage, from backend/:
#     uv run python -m scripts.c4_rank --events <events.json> --graph <graph.json> \
#         [--adr-index <dir|file>] [--no-adr] [--topsis-mode classic] [--repo <clone>] \
#         [--source-paths <mapping.json>] [--data-provenance fixture] [--run-id <id>]

import argparse
import datetime as dt
import json
import logging
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.components.degradation_scoring import DegradationScoringService
from app.components.degradation_scoring.config import C4Config
from app.core.config import settings
from app.core.logging import HANDLER_NAME, configure_logging
from app.domain.severity_report import DataProvenance

BACKEND_ROOT = Path(__file__).resolve().parents[1]
LOG_FILE = Path("logs") / "c4.jsonl"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="C4: rank degradation events, write the report")
    parser.add_argument("--events", type=Path, required=True, help="C3 event payloads (JSON list)")
    parser.add_argument("--graph", type=Path, required=True, help="release package or graph JSON")
    parser.add_argument(
        "--adr-index", type=Path, help="ADR folder (*.md + adr_links*.json) or index JSON"
    )
    parser.add_argument("--no-adr", action="store_true", help="ADR-violation criterion off")
    parser.add_argument("--topsis-mode", choices=["fixed_reference", "classic"])
    parser.add_argument("--repo", type=Path, help="full clone with tags; turns hotspot on")
    parser.add_argument("--db-cache", action="store_true", help="cache mined history in Postgres")
    parser.add_argument("--source-paths", type=Path, help="manual element -> paths mapping JSON")
    parser.add_argument(
        "--data-provenance",
        choices=[p.value for p in DataProvenance],
        default=DataProvenance.FIXTURE.value,
    )
    parser.add_argument("--run-id", help="default: run-<UTC timestamp>")
    parser.add_argument("--outputs-root", type=Path, help="default: settings.scoring_outputs_root")
    return parser.parse_args(argv)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def adr_document(path: Path) -> Any:
    # a folder: ADR files "0001-x.md" -> "ADR-0001" plus the links file; a file: the document
    if path.is_file():
        return read_json(path)
    adrs = [
        {"id": f"ADR-{item.name[:4]}", "text": item.read_text(encoding="utf-8")}
        for item in sorted(path.glob("*.md"))
    ]
    links = sorted(path.glob("adr_links*.json"))
    return {"adrs": adrs, "links": read_json(links[0])["links"] if links else {}}


def code_commit() -> str | None:
    # HEAD of this checkout, "-dirty" when there are uncommitted changes
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(BACKEND_ROOT), *args], capture_output=True, text=True
        ).stdout.strip()

    head = git("rev-parse", "HEAD")
    if not head:
        return None
    return head + ("-dirty" if git("status", "--porcelain") else "")


def history_ports(args: argparse.Namespace) -> dict[str, Any]:
    # the git history source (and optionally the Postgres cache) only when a repo is given
    if args.repo is None:
        return {}
    from app.infrastructure.git.history import PyDrillerHistorySource

    ports: dict[str, Any] = {"history_source": PyDrillerHistorySource()}
    if args.db_cache:
        from sqlalchemy.orm import sessionmaker

        from app.infrastructure.postgres.database import engine
        from app.infrastructure.postgres.repositories.mining_cache_repository import (
            PostgresMiningCache,
        )

        ports["mining_cache"] = PostgresMiningCache(sessionmaker(bind=engine))
    return ports


def log_to_file(path: Path) -> logging.Handler:
    # a second JSON-lines handler next to the team's stderr one, same format
    path.parent.mkdir(parents=True, exist_ok=True)
    team = next(h for h in logging.getLogger().handlers if h.get_name() == HANDLER_NAME)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(team.formatter)
    logging.getLogger().addHandler(handler)
    return handler


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging()
    run_id = args.run_id or "run-" + dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    config = C4Config.from_settings(settings)
    updates: dict[str, Any] = {}
    if args.outputs_root:
        updates["outputs_root"] = args.outputs_root
    if args.topsis_mode:
        updates["topsis_mode"] = args.topsis_mode
    config = config.model_copy(update=updates)

    mapping = read_json(args.source_paths) if args.source_paths else None
    pending_log = config.outputs_root / f".{run_id}.c4.jsonl"
    handler = log_to_file(pending_log)
    try:
        result = DegradationScoringService(config, **history_ports(args)).rank(
            read_json(args.events),
            read_json(args.graph),
            run_id=run_id,
            data_provenance=DataProvenance(args.data_provenance),
            adr_document=None
            if args.no_adr or not args.adr_index
            else adr_document(args.adr_index),
            repo_path=args.repo,
            code_commit=code_commit(),
            source_paths=mapping["elements"] if mapping else None,
            path_mapping=mapping.get("data_provenance", "manual-mapping") if mapping else None,
        )
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()
    log_path = result.outputs.directory / LOG_FILE
    log_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(pending_log, log_path)

    report = result.report
    print(
        json.dumps(
            {
                "run_id": run_id,
                "outputs": result.outputs.directory.as_posix(),
                "data_provenance": report.data_provenance.value,
                "active_dimensions": [d.value for d in report.active_dimensions],
                "topsis_mode": result.run.scoring.topsis_mode,
                "ranked": len(report.records),
                "skipped": len(report.skipped),
                "quarantined": len(report.quarantined),
                "top_5": [
                    {"rank": r.rank, "event_id": r.event_id, "severity": round(r.severity, 4)}
                    for r in report.records[:5]
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
