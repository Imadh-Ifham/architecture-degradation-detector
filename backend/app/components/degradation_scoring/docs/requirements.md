# C4 Requirements — Severity Ranking & Audited Explanation

Component 4 (`degradation_scoring`) of J26-SE-332. Rules: `../CLAUDE.md`. Decisions:
`decisions/`. Every requirement below has a pass/fail condition; the traceability matrix
(§5) links each one to the module and test that prove it, and is updated when a task
finishes.

**Tiers** (TRACKER §B): **A** = must, demoed live at PP1 · **B** = should, run on a pilot
at PP1 · **C** = stretch · **Post-PP1** items carry the plan month they are due.

---

## 1. Personas

| ID | Persona | Goal | Pain today |
|---|---|---|---|
| P1 | **Maintenance tech lead** of a long-lived system | Decide which architectural problems to fix first in the next release | C3 reports many degradation events as a flat list; nothing says which ones matter most or why |
| P2 | **Researcher / PP1 panel examiner** | Judge whether the ranking and explanations can be trusted | Severity scores in tools are opaque; LLM explanations can sound right while inventing facts |
| P3 | **Upstream producer** (C3 owner, Thisuri) | Have C3's events consumed as published, without adapters | Contract mismatches surface late, as crashes or silently dropped events |

## 2. User stories

| ID | Story | Persona | FRs |
|---|---|---|---|
| US-01 | As a tech lead, I want events ranked by severity, so that I can fix the most harmful ones first | P1 | FR-04–FR-10 |
| US-02 | As a tech lead, I want to see *why* an event ranks where it does (each dimension's share), so that I can argue for the fix | P1 | FR-10, FR-11 |
| US-03 | As a tech lead, I want a short explanation that cites its evidence, so that I can check it in seconds | P1 | FR-13, FR-15 |
| US-04 | As a tech lead, I want the ranking to still work when my project has no ADRs, so that the tool fits a real codebase | P1 | FR-06 |
| US-05 | As a researcher, I want every number in the report to be regenerable from a manifest, so that results are reproducible | P2 | FR-12 |
| US-06 | As a researcher, I want the ranking compared against refactorings developers actually made, so that I know it predicts real attention | P2 | FR-16–FR-18 |
| US-07 | As a researcher, I want explanations audited claim by claim against an ungrounded baseline, so that I can see how much grounding helps | P2 | FR-14, FR-15 |
| US-08 | As the C3 producer, I want C4 to read `DegradationEventV2` unchanged and report what it rejected and why, so that I can fix my side quickly | P3 | FR-01, FR-03 |
| US-09 | As the C3 producer, I want events my review rejected, or judged intentional, never to be ranked, so that C4 respects C3's decisions | P3 | FR-01 |

## 3. Functional requirements

| ID | Requirement | Pass/fail condition | Tier | Spec |
|---|---|---|---|---|
| FR-01 | Validate every C3 payload against `DegradationEventV2` and apply the eligibility rules | Each malformed fixture payload is quarantined with `malformed_payload` and its validation error, and no exception escapes. Valid events are skipped with the designed reason: `rejected`, `intentional`, `system_scope_not_rankable`, `superseded`, and `not_confirmed` only when `scoring_rank_only_confirmed=true`. Counts per reason equal the fixture design exactly | A | §4.1, ADR-007 |
| FR-02 | Load the release package C3 analysed for (`system_id`, `window.end_release`) as a directed graph; node-link JSON / GraphML for test graphs | "A → B" means A depends on B: the dependents of X equal `nx.ancestors(G, X)` in a unit test. Round trip preserves nodes, edges and `weight`. A second load of the same (system, release) is served from memory | A | §4.3 |
| FR-03 | Resolve each event's elements to graph nodes, and report the resolution rate | The fixture yields the designed split of exact / path-prefix (confidence 0.7) / unresolved. Unresolved events are quarantined `unresolved_element`. `resolution_rate` equals resolved ÷ eligible | A | §5.1 |
| FR-04 | Compute blast-radius features: fan-in ratio, PageRank, betweenness, depth | Values on star, chain, cycle and diamond graphs match hand-computed values to 1e-6. The sampled path (n > 5000) is deterministic with seed 42. Depth works on a fully cyclic graph (via condensation) | A | §5.1 |
| FR-05 | Compute hotspot features from git history between the first-seen and detected release: decayed churn, authors, coupling, bug-fix ratio | On a tiny `tmp_path` repo with fixed dates, each feature matches a hand-computed value. λ, θ, half-life and `max_files_per_commit` appear in the result metadata. Re-mining a cached range does not call the history source. Elements without paths are flagged | A | §5.2, ADR-007 A1/A4 |
| FR-06 | Compute the ADR/decision-violation weight when a decision source exists; otherwise deactivate the dimension | With no decision source, the report has `adr_violation.active=false` and weight 0 on every record, the other weights renormalise to sum to 1, and the pipeline completes | A | §5.3, ADR-007 A5 |
| FR-07 | Compute persistence from C3's data only: consecutive releases and growth slope | Tests cover a gap in releases, a single release, missing history (fallback flagged `presence_fallback=true`) and a series with fewer than two values (`growth_slope_available=false`). No trend test (Mann-Kendall etc.) is called anywhere in C4 | A | §5.4, ADR-007 A2 |
| FR-08 | Normalise features robustly per system, with small-n fallback and frozen calibration | One extreme value does not flatten the others (winsorised P5–P95). With n < 10, mode is `minmax_small_n`. Bounds saved then loaded give identical normalised values on a changed event set | A | §5.5 |
| FR-09 | Derive criteria weights with AHP and refuse inconsistent judgements | A published textbook example reproduces its weights and CR to 2 d.p. A matrix with CR > 0.10 raises `InconsistentJudgementsError`. A non-reciprocal matrix is rejected. Provenance appears in the report | A | §5.6 |
| FR-10 | Rank events with fixed-reference TOPSIS (default) and classic TOPSIS, with per-criterion contributions | Hand-computed 3×3 example matches. Scores lie in [0, 1]. Raising one criterion never lowers its event's score in fixed mode (property test). On a constructed case, adding an event flips a pair in classic mode but never in fixed mode. Classic mode matches `pymcdm` to 1e-9 | A | §5.7 |
| FR-11 | Write a schema-valid JSON report and a readable HTML report with the per-dimension breakdown | `c4_report.json` validates against `SeverityReportV1` and the committed JSON Schema. The HTML shows rank, severity, dimensions, contributions, active dimensions, weights version + CR, quarantine/skip lists and resolution rate, plus a fixture banner when `data_provenance` is a fixture | A | §4.2 |
| FR-12 | Write a run manifest for every run | The manifest holds every field in CLAUDE.md §6. Rerunning from its inputs and settings reproduces the report (see NFR-01). Outputs are written under `scoring_outputs_root`, never inside the repo | A | §6 |
| FR-13 | Generate a grounded explanation for the top-N events, citing evidence | Only the top `scoring_explain_top_n` records get an explanation. Every factual sentence ends with ≥ 1 `[E#]` that exists in the record's evidence. ≤ 120 words. Unit tests use `MockLLM` only | B | §5.9 |
| FR-14 | Generate an ungrounded baseline explanation for the same events | Same question, given only event id, type, element names and rank. It goes through the identical audit path | B | §5.9 |
| FR-15 | Audit each explanation claim by claim | A claim with a number absent from its cited evidence is `contradicted` by the deterministic check before NLI. The NLI label order is verified in a test. `groundedness = grounded ÷ total` for both conditions. `audit_sample.csv` is exported | B | §5.9 |
| FR-16 | Build ground-truth labels from refactorings developers later made (RefactoringMiner) | A label file with provenance for one release window of the demo repo. Label density (positives ÷ events) is reported. If Java/RM is unavailable: parser tests on a recorded RM sample and the task marked blocked | B | §5.10 |
| FR-17 | Report nDCG@k, P@k, MAP, Kendall τ, Spearman ρ with bootstrap CIs | Toy cases match hand computation and `sklearn` / `pytrec_eval`. τ and ρ match `scipy`. 1,000 resamples with seed 42 give identical CIs on rerun | B | §5.10 |
| FR-18 | Compare against baselines and ablate each dimension | One command produces random and structural-only baselines, the 4-row Δ-nDCG@10 ablation with CIs, and the criteria correlation matrix | B | §5.10 |
| FR-19 | LambdaMART comparator behind the same ranking interface | PP1: smoke test on fixture labels, selectable via `scoring_method`. No metrics are reported as findings before real labels exist (plan **M5**) | C | §5.8 |
| FR-20 | Survey agreement analysis | Krippendorff α and the survey reference ranking compared to the model with τ/ρ, on a synthetic response file until the survey runs (plan **M7**) | C | §5.10 |

## 4. Non-functional requirements

| ID | Quality | Measurable target | How it is checked |
|---|---|---|---|
| NFR-01 | Reproducibility | Identical inputs + settings ⇒ byte-identical `c4_report.json` apart from `run_id` and timestamp. Every figure on a slide is regenerable from a saved manifest | Golden-file test (T20); manifest beside each figure in `docs/pp1/figures/` |
| NFR-02 | Graceful degradation | The pipeline completes end-to-end (1) with AV inactive, (2) with no `AI_API_KEY` (`--no-explain`), (3) on fixtures only, with no network or database | One test per case (T16, T20, T22) |
| NFR-03 | Performance | Ranking 500 events ≤ **30 s** on cached features. Re-mining a cached commit range ≤ **10 %** of the first run's time | Timed run logged on the owner's laptop (T14, T20) |
| NFR-04 | Testability | Line coverage ≥ **80 %** for `app.components.degradation_scoring` plus C4's domain contract and scripts. No network in unit tests (real-model tests marked `live`, deselected by default) | `scripts/c4_quality_gate.ps1` report in `docs/pp1/evidence/` |
| NFR-05 | Maintainability | 0 findings from ruff (team rules + `I,UP,B,SIM,N,RUF`), ruff format and mypy strict on C4 paths. Layer-boundary test passes (no forbidden imports, no subcomponent importing another) | Gate script; `test_layer_boundaries.py` |
| NFR-06 | Cost | ≤ 2 × `scoring_explain_top_n` LLM calls per run (grounded + baseline), each cached by the team client; tokens logged. ≤ 20 real calls per development session | Manifest call count; client cache test (T22) |
| NFR-07 | Security | 0 secrets, cached responses, cloned repos or run outputs in git. Keys only via environment / `backend/.env` | `git grep` for key patterns returns nothing; outputs root is outside the repo and git-ignored |
| NFR-08 | Portability | Runs on Python **3.13** on Windows and Linux; paths via `pathlib` only | Gate script passes on Windows; on Linux once CI exists (T04, blocked) |

## 5. Traceability matrix

Status: ✅ done · ◐ partly done · — not started. Updated at the end of every task.

| Req | Module(s) | Test(s) | Task | Status |
|---|---|---|---|---|
| FR-01 | `ingestion/events.py` | `ingestion/test_events.py` | T08 | ✅ |
| FR-02 | `ingestion/graph.py` | `ingestion/test_graph.py` | T09 | ✅ |
| FR-03 | `ingestion/resolution.py` | `ingestion/test_resolution.py` | T10 | ✅ |
| FR-04 | `features/blast_radius.py`, `features/service.py` | `features/test_blast_radius.py`, `features/test_blast_radius_prototype.py`, `features/test_service.py` | T11, T17 | ✅ raw features (T11); combined BR criterion value (T17) |
| FR-05 | `features/history.py`, `features/hotspot.py`, `infrastructure/git/history.py`, `infrastructure/postgres/repositories/mining_cache_repository.py` | `features/test_history.py`, `features/test_hotspot.py`, `tests/infrastructure/git/test_history.py`, `tests/infrastructure/postgres/test_mining_cache_repository.py` | T12, T13 | ◐ history + cache (T12); features pending (T13) |
| FR-06 | `ingestion/adr.py`, `features/adr_weight.py` | `features/test_adr_weight.py` | T16 | — |
| FR-07 | `features/persistence.py` | `features/test_persistence.py` | T15 | — |
| FR-08 | `scoring_engine/normalizer.py`, `scoring_engine/service.py`, `service.py` (`scoring_inputs`) | `scoring_engine/test_normalizer.py`, `scoring_engine/test_service.py`, `test_service.py` | T17 | ✅ (C4-ADR-013) |
| FR-09 | `scoring_engine/ahp.py`, `scoring_engine/service.py` (`weights`), `scoring_engine/weights/ahp_v1.json`, `app/domain/severity_report.py` (`weights_provenance`) | `scoring_engine/test_ahp.py`, `scoring_engine/test_service.py`, `tests/domain/test_severity_report.py` | T18 | ✅ (C4-ADR-014); weights provisional until Y05 |
| FR-10 | `scoring_engine/topsis.py`, `scoring_engine/service.py` (`rank`), `service.py` (`score_rows`), `infrastructure/postgres/models/c4_scoring_run.py` (`c4_event_scores`), `alembic/versions/0004_c4_event_scores.py` | `scoring_engine/test_topsis.py`, `scoring_engine/test_service.py`, `test_service.py`, `tests/infrastructure/postgres/test_scoring_run_repository.py` | T19 | ✅ (C4-ADR-002) |
| FR-11 | `app/domain/severity_report.py`, `scripts/scoring_export_schemas.py`, `reporting/writer.py` | `tests/domain/test_severity_report.py`, `tests/scripts/test_scoring_export_schemas.py`, `reporting/test_writer.py` | T05, T20 | ◐ contract + schema (T05; 1.1.0 adds `weights_provenance`, T18); writer pending |
| FR-12 | `reporting/manifest.py` | `reporting/test_manifest.py` | T20 | — |
| FR-13 | `explanation/evidence.py`, `retriever.py`, `generator.py` | `explanation/test_generator.py` | T23, T24 | — |
| FR-14 | `explanation/baseline.py` | `explanation/test_baseline.py` | T24 | — |
| FR-15 | `explanation/auditor.py` | `explanation/test_auditor.py` | T25 | — |
| FR-16 | `evaluation/ground_truth.py`, `infrastructure/refactoring_miner/` | `evaluation/test_ground_truth.py` | T29 | — |
| FR-17 | `evaluation/metrics.py`, `bootstrap.py` | `evaluation/test_metrics.py`, `test_bootstrap.py` | T27 | — |
| FR-18 | `evaluation/baselines.py`, `ablation.py` | `evaluation/test_ablation.py` | T28 | — |
| FR-19 | `scoring_engine/lambdamart.py` | `scoring_engine/test_lambdamart.py` | T31 | — (M5) |
| FR-20 | `evaluation/survey.py` | `evaluation/test_survey.py` | T34 | — (M7) |
| NFR-04/05 | all C4 paths | gate script, `test_layer_boundaries.py` | T02, T03 | ✅ gates in place; re-checked every task |
| NFR-08 | all C4 paths | gate script (Windows) | T03, T04 | ◐ Windows only |

Test paths are relative to `backend/tests/components/degradation_scoring/` unless they
start with `tests/`.
