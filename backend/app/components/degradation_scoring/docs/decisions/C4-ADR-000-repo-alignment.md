# C4-ADR-000 — Align C4 with the group repository

- **Status:** Proposed (awaiting owner review)
- **Date:** 2026-10-14
- **Task:** C4-T01 Repo audit
- **Author:** Dahami (C4 owner), drafted with Claude Code

## Context

`CLAUDE.md` (the C4 operating manual) was written against an *assumed* group
layout: a Python 3.11 modular monolith with top-level packages `shared/`,
`c1_extraction/` … `c4_severity/`, a `config.toml`, an `archguard` CLI and
SQLite. `CLAUDE.md` §3 says that if the real repo differs, C4 follows the real
repo's conventions and records the difference here.

The real repo (audited on `develop` at `a04f99f`) is a **FastAPI backend plus a
Vite/React frontend**, governed by `INSTRUCTIONS.md` (workflow + the §7 file
placement contract) and `ARCHITECTURE.md` (intended design). Its rules are
binding on every component, so they win over `CLAUDE.md` wherever the two
conflict. `CLAUDE.md`'s *research* content (§1, §2, §5 formulas, §11 Definition
of Done) is unaffected: only *where* things live and *how* they are wired changes.

### What the audit found

| Item checked (TRACKER T01) | Status | Detail |
|---|---|---|
| Top-level `c4_severity/`, `shared/`, `c1_…`–`c3_…` packages | **Missing / differs** | Components live at `backend/app/components/<component>/`. C4's slot is `degradation_scoring/` (currently only `.gitkeep`). |
| `shared/config.py` | **Differs** | `backend/app/core/config.py` — one `pydantic-settings` `Settings` class, env vars + `backend/.env`. No `config.toml`. |
| `shared/contracts/` | **Differs** | Cross-component models go in `backend/app/domain/<name>.py`. Only `domain/repository.py` exists (a frozen dataclass). |
| `shared/llm_client.py` | **Missing** | `backend/app/infrastructure/ai/` is *planned* (ARCHITECTURE §5) but not created. |
| `shared/graph_io.py` | **Missing** | Architecture graphs are meant to live in **Neo4j** (INSTRUCTIONS §6); only the connection layer `infrastructure/neo4j/database.py` exists. |
| `shared/repo.py` | **Partly exists** | `infrastructure/git/client.py` (`GitClient`, subprocess git) and C1's `repository_ingestion` clone workspace (`REPOSITORIES_ROOT`). |
| `shared/logging.py` | **Missing** | No logging setup in `app/core/`; `structlog` is not a dependency. |
| `shared/embeddings.py` | **Missing** | Would belong to the planned `infrastructure/ai/`. |
| `pyproject.toml` extras | **Differs** | `backend/pyproject.toml`, managed by **uv**: `[project].dependencies` + `[dependency-groups] dev`. No optional extras, no `[tool.*]` sections (no ruff/mypy/coverage config). `requires-python >= 3.13`. |
| CI | **Missing** | No `.github/`. INSTRUCTIONS §3.3 nevertheless says "CI must be green". |
| Existing C4 content | **None** | `degradation_scoring/` is empty. The old `prototype.py` (TRACKER T07, T11) is not in the repo. |
| C2/C3 fixtures or sample outputs | **None** | `architecture_validation/` and `degradation_detection/` are empty. Only C1 test fixtures exist (`backend/tests/fixtures/multi_service_repo/`). |
| Migrations | **Scaffold only** | `backend/alembic/` exists; `alembic/versions/` does not (no tables yet). |
| Reference system | **New constraint** | INSTRUCTIONS §5 fixes the research target: Google **Online Boutique** (`microservices-demo`), a polyglot set of ~10 microservices. See Open issue O1. |

## Decision

C4 is implemented as the `degradation_scoring` component and obeys
INSTRUCTIONS §7 in full. The mapping below replaces `CLAUDE.md` §3's layout.

### 1. Assumption → repo rule mapping

| # | `CLAUDE.md` assumption | Real repo rule (source) | C4 decision |
|---|---|---|---|
| 1 | Top-level package `c4_severity/` | "Do not invent a new top-level folder." Components live in `app/components/<component>/` (INSTRUCTIONS §7.2, §7.6 item 7; ARCHITECTURE §2) | Code lives in `backend/app/components/degradation_scoring/`. |
| 2 | Five layers as nested folders with any number of files (`ingest/`, `features/`, `scoring/`, `explain/`, `eval/`, `report/`) | One folder = one subcomponent, each with `__init__.py` + `service.py` (one class, one public entry method) + `models.py`; max depth `components/<c>/<sub>/`; extra **private modules** allowed, never nested subcomponents (INSTRUCTIONS §7.3 rules 1–2) | Six subcomponents: `ingestion/`, `features/`, `scoring_engine/`, `explanation/`, `evaluation/`, `reporting/`. Each formula module (`blast_radius.py`, `ahp.py`, `topsis.py`, …) becomes a private module of its subcomponent. |
| 3 | `pipeline.py` orchestrator; layers call each other | The component's `service.py` orchestrates; subcomponents never import each other (INSTRUCTIONS §7.3 rule 4) | `degradation_scoring/service.py` → `DegradationScoringService` runs ingest → features → scoring → explain → report and passes artifacts between subcomponents. |
| 4 | `models.py` with all internal models | Model used by one subcomponent → that subcomponent's `models.py`; shared within the component → component `models.py`; shared by ≥ 2 components → `app/domain/` (INSTRUCTIONS §7.2) | `FeatureVector`, `SeverityRecord` etc. → `degradation_scoring/models.py`; per-step types in each subcomponent's `models.py`. |
| 5 | Input contract `shared/contracts/degradation_event.py` (co-owned with C3) | Model shared by two or more components → `app/domain/<name>.py` (INSTRUCTIONS §7.2) | `app/domain/degradation_event.py`. Co-ownership rule with C3 unchanged: edit only with explicit approval. Until C3 publishes it, a **PROVISIONAL** mirror lives in `degradation_scoring/models.py`. |
| 6 | Output contract `shared/contracts/severity_report.py` | Same row; and `infrastructure/` may import `domain/` but never `components/` (INSTRUCTIONS §7.1) — so anything an infrastructure repository persists must be a domain model | `app/domain/severity_report.py` (C4-owned). |
| 7 | Pydantic v2 for every contract | Precedent: `domain/repository.py` is a frozen dataclass; Pydantic is used in subcomponent `schemas.py` and `core/config.py`. `domain/` may import only `shared/` among app layers (INSTRUCTIONS §7.1) | Keep Pydantic v2 for C4 contracts (it is a third-party library, not an app layer). Flagged as O4 for team confirmation. |
| 8 | C3 events arrive as a JSON file (`--events`) | Degradation findings are research metadata stored in **PostgreSQL** (INSTRUCTIONS §6; ARCHITECTURE §6); outside access goes through a Protocol in `ports.py` implemented in `infrastructure/` (INSTRUCTIONS §7.1, §7.2) | Port `DegradationEventSource`. Implementations: JSON-file reader (fixtures, demo, until C3 persists) and a Postgres repository once C3 owns a findings table. |
| 9 | Validated graph from node-link JSON / GraphML (`graph_ref` = file path) | Architecture graphs live in **Neo4j** (INSTRUCTIONS §6; ARCHITECTURE §6); components must not import `neo4j` (INSTRUCTIONS §7.1) | Port `ArchitectureGraphSource` returning an in-memory `networkx.DiGraph`. Implementations: node-link JSON reader (fixtures) and `Neo4jArchitectureGraphRepository` once C2 publishes its graph schema. `graph_ref` semantics become "(system, release) key", to be confirmed with C2/C3 (Y02, Y03). Edge-direction rule (§4.3) unchanged. |
| 10 | ADR index file from C2 | ADR extraction is C2's subcomponent (ARCHITECTURE §3.2, §4.2); cross-component access via ports (INSTRUCTIONS §7.1) | Port `AdrIndexSource`; AV stays optional and inactive when the port returns nothing. |
| 11 | `config.toml [c4]` → `C4Config` | Settings and environment config → `app/core/config.py` (INSTRUCTIONS §7.2); precedent: prefixed field blocks (`inventory_*`) | Add a `scoring_*` block to `Settings` (env vars `SCORING_*`), e.g. `scoring_cochange_threshold=5`, `scoring_explain_top_n=10`. A thin `C4Config` view inside the component reads from it. No `config.toml`. |
| 12 | SQLite cache for mining rows and LLM generations (`infra/cache.py`; ADR-006) | Exactly two databases: Postgres for "research runs … scoring results … audit and provenance records" (INSTRUCTIONS §6; ARCHITECTURE §6); `sqlalchemy` forbidden in components (INSTRUCTIONS §7.1); tables in `infrastructure/postgres/models/`, queries in `infrastructure/postgres/repositories/`, migrations in `backend/alembic/versions/` (INSTRUCTIONS §7.2) | Ports `MiningCache` and `GenerationCache`; Postgres repositories implement them; unit tests use in-memory fakes. **Supersedes the planned C4-ADR-001 (SQLite over Parquet)** — new C4-ADR-001 "Postgres-backed caches behind ports". Graph centralities stay memoised in-process per (system, release). |
| 13 | PyDriller called directly in `ingest/history.py` | Infrastructure holds "database, AI and external-tool adapters"; precedent `infrastructure/git/client.py` wraps git (INSTRUCTIONS §7.1; ARCHITECTURE §2) | Port `CommitHistorySource`; PyDriller adapter in `app/infrastructure/git/`. All hotspot maths (decay, coupling, bug-fix ratio) stays pure in `features/hotspot.py`. |
| 14 | `infra/llm.py` adapter importing `anthropic`; `MockLLM` | Vendor LLM SDK only in `app/infrastructure/ai/providers/`; components go through the AI interface with per-task model selection (INSTRUCTIONS §7.1, §7.2; ARCHITECTURE §5) | Port `TextGenerator` in `ports.py`. `anthropic` provider in `infrastructure/ai/providers/anthropic_provider.py`; model id in `infrastructure/ai/model_configuration.py`. `MockLLM` (canned `[E#]` text) lives in the component so `--no-explain`/offline runs and tests need no network. |
| 15 | sentence-transformers encoder + NLI cross-encoder used directly in `explain/` | "All AI usage goes through the AI interface" (ARCHITECTURE §5) | Ports `TextEmbedder` and `EntailmentJudge`, implemented in `infrastructure/ai/`. FAISS index-building stays in `explanation/` (it is numeric, not a model). Inference-only rule (§2) unchanged. |
| 16 | Prompts in `explain/prompts/*.txt` | Prompt templates → `app/components/<c>/<sub>/prompts.py` (INSTRUCTIONS §7.2) | `explanation/prompts.py` with versioned constants (`GROUNDED_V1`, `UNGROUNDED_V1`); the version string and sha256 still go in the manifest. |
| 17 | RefactoringMiner subprocess in `eval/ground_truth.py` | External tools are infrastructure adapters (INSTRUCTIONS §7.1) | Port `RefactoringDetector`; subprocess adapter in `app/infrastructure/refactoring_miner/` (no §7.2 row — raise in the PR). Label-building rule stays in `evaluation/`. |
| 18 | `report/writer.py` writes JSON + HTML; outputs in repo `outputs/` | Precedent: C1's `repository_inventory/writer.py` writes JSON from inside a subcomponent. Paths come from settings (precedent `repositories_root`); never commit outputs | `reporting/` writes `c4_report.json`, `c4_report.html` (Jinja2), `c4_quarantine.json`, `c4_run_manifest.json` under `settings.scoring_outputs_root/<system>/<run_id>/` (default: system temp dir). |
| 19 | Manifest is a file only (`infra/manifest.py`) | Postgres holds "research runs … audit and provenance records" (ARCHITECTURE §6) | Manifest built in `reporting/manifest.py`, written to file (slide reproducibility) **and** persisted as a run record through a `ScoringRunRepository` port once a migration exists. File output alone is enough for PP1. |
| 20 | `archguard rank` Click CLI; `python -m c4_severity` | No CLI exists. HTTP endpoint → `app/api/<feature>.py`, schemas → `app/api/schemas/<feature>.py`, wiring → `app/api/dependencies.py` (INSTRUCTIONS §7.2); "A dev or ops script → `backend/scripts/`" (INSTRUCTIONS §7.2) | `POST /degradation-scoring/runs` in `app/api/degradation_scoring.py` (frontend path). Demo/eval entry points as scripts: `backend/scripts/c4_rank.py`, `backend/scripts/c4_eval.py` (stdlib `argparse`, so `click` is dropped). The live demo uses the script. |
| 21 | `structlog` JSON logging; `c4_severity/infra/log.py` | Logging is a `core/` concern (INSTRUCTIONS §7.1); nothing exists yet | Use stdlib `logging.getLogger(__name__)` now; propose a JSON formatter in `app/core/` to the team (O5). Drop `structlog` from the C4 list unless the team adopts it. |
| 22 | `c4_severity/errors.py` | Precedent: per-subcomponent `errors.py` (`repository_ingestion/errors.py`) | `errors.py` in each subcomponent that raises (e.g. `scoring_engine/errors.py` → `InconsistentJudgementsError`). |
| 23 | Tests in `c4_severity/tests/unit/…` | Tests mirror the source tree: `app/x/y.py` → `tests/x/test_y.py`, `__init__.py` everywhere; every `service.py` ships with its test (INSTRUCTIONS §7.5) | `backend/tests/components/degradation_scoring/<sub>/test_<module>.py`; adapters under `backend/tests/infrastructure/…`. |
| 24 | Fixtures in `c4_severity/fixtures/` | Precedent: `backend/tests/fixtures/<name>/`, excluded from collection by `tests/conftest.py` | `backend/tests/fixtures/degradation_scoring/` (events, malformed, graphs, adr, labels, golden). `"data_provenance": "fixture"` rule unchanged. |
| 25 | `scoring/weights/ahp_v1.json` | No §7.2 row for data files | Keep it as `scoring_engine/weights/ahp_v1.json` (package data, not code) and raise it in the PR. Provenance rule unchanged (`provisional-author-elicited`). |
| 26 | Docs in `c4_severity/docs/` | No §7.2 row for component docs | Owner decision 2026-10-14: `backend/app/components/degradation_scoring/docs/` (decisions/, TRACKER.md, learning-notes.md, requirements.md, risk-register.md, pp1/, schemas/). Contains no Python, so no `__init__.py` (§7.3 rule 6 applies to code folders — confirm in the PR). |
| 27 | `CLAUDE.md` at `c4_severity/CLAUDE.md` | A root `CLAUDE.md` would apply C4 rules to every teammate's Claude Code session | Move it to `backend/app/components/degradation_scoring/CLAUDE.md` (Claude Code loads nested CLAUDE.md files when working in that folder). Optionally keep a git-ignored `CLAUDE.local.md` at the root that points to it. |
| 28 | Python 3.11 | `requires-python >= 3.13`; `.python-version` = 3.13 | Python 3.13. All formulas unchanged. |
| 29 | `pip install -e ".[c4]"`; `[project.optional-dependencies] c4` | uv-managed `backend/pyproject.toml` with `[dependency-groups]`; team-owned file | See §3 below. Any edit to `pyproject.toml` beyond adding C4 packages needs team agreement. |
| 30 | `ruff`, `ruff format`, `mypy --strict`, `pytest-cov` gates | No tool configured | Add `[tool.ruff]`, `[[tool.mypy.overrides]]` scoped to `app.components.degradation_scoring.*` (mypy cannot set `strict` per module, so the strict flags are listed individually), and coverage settings. Gates run on C4 paths only. Team-owned file: raise in the PR. |
| 31 | `.github/workflows/` C4 job | No `.github/`; INSTRUCTIONS §3.3 requires green CI | Do not create CI unilaterally (O6). Meanwhile a local gate script `backend/scripts/c4_quality_gate.ps1` runs the four gates and saves its output as evidence. |
| 32 | Branch `feat/c4-<task-id>-<slug>`; Conventional Commits; "never push to main"; owner merges | `<type>/<short-kebab-description>` (INSTRUCTIONS §3.1); no `main` — PRs go to `develop` (§1.1, §1.2, §3.2); ≥ 1 review approval, **squash-merge**, delete branch (§3.3); scope optional (§2.1) | Compatible. Branches `feat/c4-<task-id>-<slug>`; scope `scoring` (matches the `recovery` example); PR to `develop`, squash-merged, so "one task per commit" becomes "one task per PR". Approval from someone other than the author (O7). |
| 33 | No module header convention | Precedent in every module: header docstring with `Author:`, `Date:`, `Description:` | C4 modules follow the same header, then Google-style docstrings citing the plan section. |
| 34 | Demo repo: "Java, ≥ 8 tags" chosen by the owner (Y04); RefactoringMiner ground truth | Research target fixed as **Online Boutique** (INSTRUCTIONS §5): Go, C#, Node.js, Python and one Java service (`adservice`) | **Not decided here** — see O1. |

### 2. Target C4 layout

```
backend/app/components/degradation_scoring/
├── __init__.py                 # re-exports DegradationScoringService only
├── service.py                  # DegradationScoringService — orchestration (was pipeline.py)
├── models.py                   # FeatureVector, SeverityRecord, EvidenceChunk, Claim, AuditResult;
│                               #   PROVISIONAL DegradationEvent mirror until app/domain has it
├── ports.py                    # DegradationEventSource, ArchitectureGraphSource, AdrIndexSource,
│                               #   CommitHistorySource, MiningCache, GenerationCache,
│                               #   TextGenerator, TextEmbedder, EntailmentJudge,
│                               #   RefactoringDetector, ScoringRunRepository
├── config.py                   # C4Config view over app.core.config.settings (scoring_* fields)
├── CLAUDE.md
├── docs/                       # decisions/, TRACKER.md, learning-notes.md, requirements.md,
│                               #   risk-register.md, pp1/, schemas/ (generated JSON Schema)
├── ingestion/                  # IngestionService: events.py, resolution.py, adr.py
├── features/                   # FeatureExtractionService: blast_radius.py, hotspot.py,
│                               #   adr_weight.py, persistence.py
├── scoring_engine/             # ScoringService: normalizer.py, ahp.py, topsis.py, lambdamart.py,
│                               #   weights/ahp_v1.json, errors.py
├── explanation/                # ExplanationService: evidence.py, retriever.py, generator.py,
│                               #   baseline.py, auditor.py, prompts.py, mock_llm.py
├── evaluation/                 # EvaluationService: ground_truth.py, metrics.py, bootstrap.py,
│                               #   baselines.py, ablation.py, survey.py
└── reporting/                  # ReportingService: writer.py, manifest.py, hashing.py,
                                #   templates/report.html.j2

backend/app/domain/degradation_event.py        # co-owned with C3 (approval required)
backend/app/domain/severity_report.py          # C4-owned
backend/app/infrastructure/ai/…                # TextGenerator / TextEmbedder / EntailmentJudge adapters
backend/app/infrastructure/git/history.py      # PyDriller CommitHistorySource
backend/app/infrastructure/postgres/{models,repositories}/…  # caches, run records
backend/app/infrastructure/refactoring_miner/  # RefactoringDetector (raise in PR)
backend/app/api/degradation_scoring.py         # POST /degradation-scoring/runs
backend/app/api/schemas/degradation_scoring.py
backend/scripts/c4_rank.py, c4_eval.py, c4_quality_gate.ps1
backend/tests/components/degradation_scoring/…  # mirrors the tree above
backend/tests/fixtures/degradation_scoring/…
```

ARCHITECTURE.md §4.2 currently plans `scoring_engine`, `severity`, `rules` for
this component. The six subcomponents above refine that plan (`severity` →
`features` + `scoring_engine`; `rules` → `scoring_engine/weights` + settings).
Updating ARCHITECTURE.md §4.2 is a team-doc change → O8.

### 3. Dependencies on Python 3.13 (checked 2026-10-14, nothing installed)

Method: `uv pip compile` (resolve only) of `backend/pyproject.toml` + the
`CLAUDE.md` §7 list, with `--python-version 3.13` for
`x86_64-pc-windows-msvc` and `x86_64-unknown-linux-gnu`, first allowing
source builds, then `--only-binary :all:` (prebuilt wheels only), then with
every currently locked backend version held as a constraint.

| Package | Resolved | Prebuilt wheel, Win + Linux, cp313 | Note |
|---|---|---|---|
| networkx | 3.7 | yes | |
| numpy | 2.5.4 | yes | |
| scipy | 1.18.1 | yes | |
| pandas | 3.0.6 | yes | |
| pydantic | ≥ 2 (already present) | yes | |
| jinja2 | — | yes | |
| pydriller | 2.12 | yes | pulls gitpython 3.2.1 |
| gitpython | 3.2.1 | yes | |
| pathspec | 1.1.1 | yes | |
| pymcdm | 1.4.0 | yes | Check its TOPSIS API before writing the cross-check (§5.7). |
| lightgbm | 4.7.0 | yes | |
| scikit-learn | 1.9.1 | yes | |
| faiss-cpu | 1.15.1 | yes | |
| sentence-transformers | 6.1.0 | yes | pulls torch 2.14.1 + transformers 5.19.0. **On Linux, default torch pulls 15 `nvidia-*` CUDA packages (several GB)** — use the CPU-only torch index for CI. Inference only → C4-ADR-005. |
| anthropic | 1.14.0 | yes | Imported only in `infrastructure/ai/providers/`. |
| **pytrec_eval** | 0.5 | **no — source only, fails without a C++ toolchain** | Replace with **`pytrec-eval-terrier` 0.5.10** (same `pytrec_eval` import, wheels for cp313 on both platforms). Keep the `sklearn.metrics.ndcg_score` cross-check from §5.10. |
| krippendorff | 0.9.0 | yes | |
| shap | 0.53.0 | yes | post-PP1 |
| structlog | 26.1.0 | yes | Not adopted (row 21). |
| click | — | yes | Not needed (row 20). |
| pytest-cov, ruff, mypy, hypothesis | — | yes | dev group |

Result: **every package except `pytrec_eval` installs from wheels on 3.13, on
both platforms, without changing any version currently pinned in
`backend/uv.lock`** (109 pins on Windows, 127 on Linux).

Proposed grouping in `backend/pyproject.toml` (team-owned → raise in the PR):

- `[project].dependencies` (needed when the API imports C4): `networkx`,
  `numpy`, `scipy`, `pymcdm`, `pydriller`, `pathspec`, `jinja2`.
- `[dependency-groups] scoring-ml` (heavy, imported lazily only by
  `explanation/`, `evaluation/`, `scoring_engine/lambdamart.py` and the AI
  adapters): `pandas`, `scikit-learn`, `lightgbm`, `faiss-cpu`,
  `sentence-transformers`, `anthropic`, `pytrec-eval-terrier`, `krippendorff`,
  `shap`. Install with `uv sync --group scoring-ml`.
- `[dependency-groups] dev` additions: `pytest-cov`, `ruff`, `mypy`,
  `hypothesis`, `gitpython` (tiny test repos).

## Alternatives considered

1. **Keep `c4_severity/` at the root as in `CLAUDE.md`.** Rejected: violates
   INSTRUCTIONS §7.2/§7.6 ("do not invent a new top-level folder"); the PR would
   be rejected.
2. **Put all C4 code in one flat subcomponent.** Rejected: one `service.py` with
   one public method cannot cleanly host five layers, and it loses the
   layer-per-subcomponent design evidence for LO3.
3. **Keep SQLite as a private C4 cache.** Rejected: ARCHITECTURE §6 says the
   system uses exactly two databases; a third store needs a team decision.
4. **Call the Anthropic SDK and sentence-transformers from the component.**
   Rejected: forbidden import (INSTRUCTIONS §7.1) and against ARCHITECTURE §5.

## Consequences

- All formulas, thresholds and defaults in `CLAUDE.md` §5 are unchanged. Only
  file locations, wiring and storage move.
- The maths (features, AHP, TOPSIS, metrics) stays pure Python with no FastAPI,
  database or SDK imports, so it is unit-testable without services. This
  separation is design evidence for LO3.
- C4 becomes the first user of several planned shared pieces
  (`infrastructure/ai/`, Postgres repositories, the first Alembic migration).
  Each needs a short team heads-up before it lands.
- `CLAUDE.md` §3, §4, §5.2, §5.9, §6, §7, §10 and TRACKER T02, T03, T04, T12,
  T20, T22 are revised to match (drafted separately, applied after owner review).
- New decision records required: C4-ADR-001 (Postgres caches behind ports,
  replacing SQLite-over-Parquet), C4-ADR-005 (torch as an inference-only runtime
  dependency; CPU-only wheels in CI), C4-ADR-006 (`pytrec-eval-terrier`
  replacing `pytrec_eval`).

## Open issues (owner / team decisions — not decided here)

| ID | Issue | Why it matters | Who |
|---|---|---|---|
| **O1** | The reference system is **Online Boutique**, a polyglot microservices demo (INSTRUCTIONS §5). TRACKER Y04 assumes a Java repo, and **RefactoringMiner only analyses Java** — it would label only `adservice`. The service graph is also small (~11 nodes), so normalisation will use `minmax_small_n`. | Ground-truth validation (§5.10) and the T29 pilot may not work on the group's target. Options: a second, Java evaluation system for C4 only; a language-agnostic ground truth (file moves/renames from git history); or a C4-specific scope note. Needs supervisor input. | Owner + supervisor |
| O2 | How C3 delivers events (Postgres table vs JSON artefact) and the graph key that replaces `graph_ref` | Decides the first real `DegradationEventSource` implementation | Y02 (C3) |
| O3 | How C2 stores the validated graph in Neo4j (labels, edge direction, `paths` attribute) and the ADR index shape | Decides `ArchitectureGraphSource` / `AdrIndexSource` and the edge-direction flag | Y03 (C2) |
| O4 | Pydantic models in `app/domain/` (current precedent is dataclasses) | Contract style for `degradation_event.py` / `severity_report.py` | Team |
| O5 | Backend-wide logging setup in `app/core/` (stdlib JSON formatter or `structlog`) | Structured logs (`logs/c4.jsonl`) | Team |
| O6 | Creating `.github/workflows/` (INSTRUCTIONS §3.3 already requires green CI) | T04 cannot finish without it | Team |
| O7 | Who approves C4 PRs (INSTRUCTIONS §3.3: ≥ 1 approval) | Merge flow | Team |
| O8 | Updating ARCHITECTURE.md §4.2 to the six C4 subcomponents; creating `infrastructure/ai/` (ARCHITECTURE §5) and `infrastructure/refactoring_miner/` | Shared architecture docs and folders | Team |
| O9 | `pyproject.toml` changes: the C4 dependency groups, the CPU-only torch index, ruff/mypy/coverage config | Team-owned file | Team |

## Addendum — 2026-10-17: re-aligned with `develop` @ `c45713f`

`develop` gained 34 commits after the audit. Four of them change decisions above:

| Change upstream | Rows affected | Revised decision |
|---|---|---|
| `49d788c` configuration split: non-sensitive tuning in a committed `backend/config.ini` (sections, flat keys), secrets and paths in `.env`; `Settings` now rejects unknown keys (INSTRUCTIONS §2.3, §6 as amended) | 11, 18 | `scoring_*` fields stay in `app/core/config.py` (prefix kept: `config.ini` flattens sections into one namespace); their values are documented in a new `[scoring]` section of `config.ini`; `scoring` added to `CONFIG_INI_SECTIONS`; `.env.example` documents only `SCORING_OUTPUTS_ROOT`. Weight vectors became scalar settings because INI values are strings. |
| Validation component writes outputs under the ignored `backend/artifacts/` (`decision_log_root`) | 18 | `scoring_outputs_root` defaults to `backend/artifacts/scoring/` instead of the system temp directory. |
| `ddcae5c` provider-agnostic AI layer: `infrastructure/ai/interface.py` (`ConfiguredAIClient` with a response cache), `model_configuration.py`, `model_registry.py`, `providers/{fake,openai_compatible}.py`; key `AI_API_KEY`; `live` pytest marker | 14, 15, O8 | C4's `TextGenerator` wraps the existing client; no Anthropic provider, no `GenerationCache` port (the client already caches); `anthropic` dropped from the dependency list. Embedder and NLI judge are still new C4 adapters in `infrastructure/ai/`. Model choice for C4 is an owner decision (TRACKER Y06). |
| `feat/degradation-detection` (C3, not yet merged) adds `app/domain/degradation_event.py` | 5, O2 | When it lands, C4-T05/T08 consume it instead of a PROVISIONAL mirror. Compare its fields with CLAUDE.md §4.1 before T05. |

Also noted: `pyproject.toml` now has `[tool.pytest.ini_options]` (the `live`
marker, deselected by default) and `pydantic`/`packaging` as direct dependencies.

## Addendum — 2026-10-18: re-aligned with `develop` @ `589cf40` (C3 merged)

C3's component (`feat/degradation-detection`) was merged into `develop`. It edited the
same shared files as C4-T03, so `pyproject.toml` and `uv.lock` conflicted; `config.ini`,
`config.py` and `.env.example` merged automatically.

| Change upstream | Effect on C4 |
|---|---|
| C3 `[tool.ruff]` for the whole backend: line length 100, rules `E, F, I, B, UP` | Replaces C4's (88). C4 code reformatted to 100; the gate still adds `SIM, N, RUF` for C4. |
| C3 `[tool.mypy]`: `strict = true` globally, scoped by a `files` list | Replaces C4's per-module strict overrides. `app/components/degradation_scoring` added to `files`; C4's `ignore_missing_imports` list kept (minus networkx, which now has stubs). The pydantic mypy plugin is **not** used, so as not to change how C3's code is checked. |
| C3 dependencies overlap C4's (networkx, numpy, scipy, sentence-transformers in C3's `rag` extra, ruff, mypy, pytest-cov, hypothesis) | Kept once. C4 adds only jinja2, pathspec, pydriller, pymcdm, gitpython and the `scoring-ml` group. |
| C3's lock had the default (CUDA) torch: 19 GPU packages incl. `triton` | The C4 CPU-only torch pin now applies project-wide: those 19 packages are gone and **no other locked version changed**. Tell C3 — their `rag` extra now installs CPU torch. |
| `app/core/logging.py` + `structlog` (C3) | Resolves **O5**: C4 logs through `structlog` with reason codes. |
| `app/domain/degradation_event.py` (C3) is on `develop` | Resolves part of **O2**: C4-T05/T08 consume it; compare with CLAUDE.md §4.1 first. |

Verified after the merge: C4 quality gate all PASS; `mypy` over C3's file list + C4:
no issues in 69 files; ruff on C3's component: clean; full suite 1543 passed (6
deselected by the `not live` marker), database tests included.
