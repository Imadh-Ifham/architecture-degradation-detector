# C4 PP1 evidence pack

One line per PP1 criterion: the claim, and the exact file or screen that proves it. Paths are
relative to `backend/app/components/degradation_scoring/` (`<C4>`) unless they start with
`backend/`, `frontend/` or `tests/` (= `backend/tests/`). Demo steps refer to
[`demo-script.md`](demo-script.md). Status as of 2026-10-19; PP1 is Thursday 22 Oct, Tier A.

## Criterion → evidence

| Criterion (LO, weight) | Claim | Proof (artifact or screen) |
|---|---|---|
| **Problem definition** (LO1, 10 % × 30 %) | C3 emits a flat, unranked list of degradation events; maintainers cannot tell which to fix first, and some events cannot be used at all | Demo step 1 (the 17-event list); `docs/requirements.md` §1 personas P1–P3 and US-01..09; quarantine/skip counts in every report (4 + 4 of 17 in the fixture run) |
| **Proof of concept** (LO1, 10 % × 70 %) | The full pipeline runs end-to-end: validate → resolve on the graph → 4 criteria → AHP → fixed-reference TOPSIS → JSON/HTML/manifest, on fixtures and on a real repository | Demo steps 2–6 and 9 (Priorities page and Score phase in the group UI); `docs/pp1/figures/t21_online_boutique/` (AV on/off reports + README with 3 bullets); `tests/fixtures/degradation_scoring/golden/fixture_report.v1.json`; `backend/scripts/c4_rank.py` |
| **Key knowledge areas** (LO2, 25 % × 30 %) | Five areas, each applied in one module | Graph theory → `features/blast_radius.py` (PageRank, betweenness, ancestors, condensation depth; C4-ADR-003, -008) · Mining software repositories → `features/hotspot.py`, `features/history.py`, `backend/app/infrastructure/git/history.py` (decayed churn, authors, change coupling, bug-fix ratio; C4-ADR-009) · Robust statistics → `scoring_engine/normalizer.py` (winsorised min-max; C4-ADR-013, -015) · MCDA → `scoring_engine/ahp.py`, `scoring_engine/topsis.py` (C4-ADR-014, -002) · IR evaluation (planned) → `docs/pp1/validation-plan.md` (nDCG@k, P@k, Kendall τ) |
| **Technologies in depth** (LO2, 25 % × 70 %) | Each tool chosen against an alternative, with known limits | "Why this, not that" below; `docs/learning-notes.md` (21 entries, one per task, each with a panel question); `docs/pp1/qa-bank.md` |
| **Design excellence** (LO3, 40 % × 20 %) | Layered component, contracts at every boundary, ports for everything external, graceful degradation, reproducibility | `CLAUDE.md` §3 layout; `ports.py` (7 Protocols); `tests/components/degradation_scoring/test_layer_boundaries.py`; `backend/app/domain/severity_report.py` + `docs/schemas/severity_report.schema.json`; AV-off path (demo step 4); manifests (`reporting/manifest.py`); 15 decision records in `docs/decisions/` |
| **Completion** (LO3, 40 % × 30 %) | Tier A complete: 22 tracker tasks done (T01–T03, T05–T21, T16b, T20b) | `docs/TRACKER.md` §E (ticked, dated, evidence per task); re-baseline note in §B; PRs #10, #11, #12, #13, #18 merged to `develop`; Tier B (explanations, evaluation) re-planned after PP1 (see Risk) |
| **Standards / best practice** (LO3, 40 % × 20 %) | Same four gates on every task; strict typing; tests with hand-computed values; Conventional Commits; PR review | Latest `docs/pp1/evidence/quality-gate-*.txt` (ruff + `I,UP,B,SIM,N,RUF`, ruff format, mypy strict, pytest: 597 passed, 99 % coverage); `backend/scripts/c4_quality_gate.ps1`; git log (`feat(scoring): …`); demo step 8 |
| **User / functional requirements** (LO3, 40 % × 20 %) | Requirements are testable, prioritised (A/B/C) and traced to code and tests | `docs/requirements.md`: 3 personas, 9 user stories, FR-01..FR-20 with acceptance criteria, NFR-01..NFR-08 with measures, traceability matrix (FR-01..FR-12 ✅) |
| **Risk mitigation** (LO3, 40 % × 10 %) | Risks are tracked with corrective actions already executed | `docs/pp1/risk-register.md` (status + executed action per risk: fixtures for upstream gaps, AV ablatable, Postgres cache, provisional AHP label, manual path mapping, read-only API) |
| **Communication** (LO4, 15 %) | Timed demo with a fallback per step; prepared answers | `docs/pp1/demo-script.md`; `backend/scripts/c4_demo.ps1` (every step ≤ 5 s); `docs/pp1/qa-bank.md` (25 Q&A); rehearsals Y08/Y09 |
| **Commercialisation** (LO5, 10 %) | Clear users, pain and benefits; positioned against existing tools; realistic delivery | `docs/pp1/commercialisation.md` |

## Why this, not that

| Choice | Instead of | Why |
|---|---|---|
| **NetworkX** | igraph / graph-tool; Neo4j GDS | Pure Python, readable and exact at service-graph size (tens of nodes), so every value is hand-checkable in a test; in-process and memoised per release, so no database is needed to rank. Above 5,000 nodes betweenness switches to seeded sampling (k = 500, seed 42). |
| **PyDriller** | parsing `git log` by hand; GitPython | Gives per-commit, per-file added/deleted lines for a tag range — exactly the input of churn, coupling and bug-fix ratio — and is a standard mining-software-repositories tool. Its cost (first mine of Online Boutique ≈ 10 min) is paid once thanks to the cache. |
| **AHP** | equal weights; direct 0–100 rating; data-driven (entropy) weights | Turns expert judgement into weights with a built-in consistency check (CR ≤ 0.10, refused above); the weights are explicit and auditable. Labelled `provisional-author-elicited` until the supervisor session (Y05). |
| **Fixed-reference TOPSIS** | weighted sum; classic TOPSIS | Measures distance to both the best and the worst possible event, not just a sum; with ideal = 1 and anti-ideal = 0 fixed, an event's score never depends on which other events are in the run, so adding an irrelevant event cannot reorder the list (demo step 7; C4-ADR-002). |
| **PostgreSQL mining cache behind a port** | Parquet / SQLite files (original plan) | The group architecture fixes two databases (PostgreSQL + Neo4j); a port (`MiningCache`) keeps the component database-free and lets unit tests use an in-memory fake (C4-ADR-001). Measured: Online Boutique run ≈ 10 min uncached → 4.5 s cached. |
| **Pydantic contracts** | plain dicts / dataclasses | Every boundary is validated: a malformed C3 payload is quarantined with its error instead of crashing; the report is re-read through `SeverityReportV1` before it is written; the same model generates the JSON Schema and, from it, the frontend's TypeScript types. |
| **Read-only API over saved reports** | a "run" endpoint; the UI reading files directly | No long-running mining jobs over HTTP for PP1; the UI shows exactly the report that the slides and manifest refer to (one source of truth); behind `SavedReportSource`, a database-backed source can replace the files later without touching the API. |

## Numbers you may quote (all fixture or pilot, regenerable)

| Number | Source |
|---|---|
| Fixture run: 17 payloads → 9 ranked, 4 skipped, 4 quarantined, resolution 0.9 | `c4_demo.ps1` → `artifacts/scoring/c4-fixture-shop/demo-adr-on/c4_run_manifest.json` |
| AHP `ahp_v1`: weights 0.47 / 0.28 / 0.16 / 0.10, CR 0.011 | `scoring_engine/weights/ahp_v1.json`; any report's manifest |
| Online Boutique: 6 fixture events on real history; E01 first with and without AV | `docs/pp1/figures/t21_online_boutique/README.md` |
| Cache: 599 s first mine (7 tag ranges) → 4.5 s whole run | `c4_demo.ps1 -Warm` then `c4_demo.ps1`, 2026-10-19 |
| 597 tests, 99 % coverage, 4/4 gates | `docs/pp1/evidence/quality-gate-*.txt` (latest) |
