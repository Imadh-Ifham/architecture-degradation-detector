# Run C4 layers 1-3 (ingestion, features, scoring) on the fixtures and save the run to
# PostgreSQL for inspection (C4-T16b, T19): tables c4_scoring_run, c4_event_ingestion,
# c4_event_features, c4_event_scores. Real-repository runs come in T21. Usage, from backend/:
#     uv run python -m scripts.c4_run_features                 # fixtures, fixture ADR index
#     uv run python -m scripts.c4_run_features --no-adr        # ADR-violation criterion off
#     then open docs/pp1/demo-queries.sql in DBeaver

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any

from sqlalchemy.orm import sessionmaker

from app.components.degradation_scoring import DegradationScoringService
from app.components.degradation_scoring.config import C4Config
from app.core.config import settings
from app.core.logging import configure_logging
from app.infrastructure.postgres.database import engine
from app.infrastructure.postgres.repositories.scoring_run_repository import (
    PostgresScoringRunRepository,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = BACKEND_ROOT / "tests" / "fixtures" / "degradation_scoring"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="C4 layers 1-3 on fixtures, saved to Postgres")
    parser.add_argument("--events", type=Path, default=FIXTURES / "events/fixture_events.v1.json")
    parser.add_argument(
        "--graph", type=Path, default=FIXTURES / "graphs/fixture_release_package.v1.5.0.json"
    )
    parser.add_argument("--adr-dir", type=Path, default=FIXTURES / "adr")
    parser.add_argument("--adr-links", type=Path, default=FIXTURES / "adr/adr_links.v1.json")
    parser.add_argument("--no-adr", action="store_true", help="run without an ADR index")
    parser.add_argument("--run-id", help="default: fixture-<UTC timestamp>")
    return parser.parse_args()


def adr_document(adr_dir: Path, links_file: Path) -> dict[str, Any]:
    # ADR files "0001-x.md" -> "ADR-0001", plus the element -> ADR links
    adrs = [
        {"id": f"ADR-{path.name[:4]}", "text": path.read_text(encoding="utf-8")}
        for path in sorted(adr_dir.glob("*.md"))
    ]
    return {"adrs": adrs, "links": json.loads(links_file.read_text(encoding="utf-8"))["links"]}


def main() -> None:
    configure_logging()
    args = parse_args()
    run_id = args.run_id or "fixture-" + dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    commit = subprocess.run(
        ["git", "-C", str(BACKEND_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    service = DegradationScoringService(
        C4Config.from_settings(settings),
        run_repository=PostgresScoringRunRepository(sessionmaker(bind=engine)),
    )
    result = service.run_features(
        json.loads(args.events.read_text(encoding="utf-8")),
        json.loads(args.graph.read_text(encoding="utf-8")),
        run_id=run_id,
        data_provenance="fixture",
        adr_document=None if args.no_adr else adr_document(args.adr_dir, args.adr_links),
        code_commit=commit or None,
    )
    outcomes = [record.outcome for record in result.ingestion.payloads]
    print(
        json.dumps(
            {
                "run_id": run_id,
                "system_id": result.system_id,
                "release_id": result.release_id,
                "payloads": len(outcomes),
                "ranked": outcomes.count("ranked"),
                "skipped": outcomes.count("skipped"),
                "quarantined": outcomes.count("quarantined"),
                "hotspot": result.features.hotspot.inactive_reason or "active",
                "adr": result.features.adr.inactive_reason or "active",
                "topsis_mode": result.scoring.topsis_mode,
                "weights": {
                    d.value: round(w, 4) for d, w in result.scoring.weights.weights.items()
                },
                "weights_provenance": result.scoring.weights.provenance.value,
                "top_5": [
                    {"rank": r.rank, "event_id": r.event_id, "severity": round(r.severity, 4)}
                    for r in result.scoring.ranking[:5]
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
