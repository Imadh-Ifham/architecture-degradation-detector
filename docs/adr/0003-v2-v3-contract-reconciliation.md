# ADR 0003 — Reconciling the v2 and v3 C3 designs

- **Status:** Accepted; R1 and R2 need sign-off from C2 and C4 before the contracts are tagged
- **Date:** 2026-10-13
- **Component:** C3 Degradation Detection
- **Source:** [implementation plan](../implementation-plan.md) Section 1.3

## Context

Two C3 designs exist. Version 2 has contracts, tests and a self-implemented statistical core.
Version 3 followed the supervisor's pivot to anti-patterns ([ADR 0002](0002-anti-patterns-over-code-smells.md))
and proposed different field names, dependencies and layout. They conflict in thirteen places.
This ADR records which side won each one.

## Decisions

| # | Topic | Decision | Reason |
|---|---|---|---|
| R1 | Input field names | Keep v2 names (`system_id`, `release_id`, `released_at`, `dependencies[{from,to,types,count}]`). Add `elements[].layer`, `datastore_access[]`, `delegation[]` as optional. Version `ReleasePackageV1.1`. | Backward compatible; existing contract tests stay valid. |
| R2 | Output event | `DegradationEventV2` (`schema_version` 2.0.0). `smell_type` becomes `anti_pattern_type`; add `scope`, `instance_id`, `members`, `lifecycle`. Keep `q_value`, `event_key`, `window`, `affected_metrics`, `context`, `review_status`, `provenance`. | Breaking change, so a major bump. |
| R3 | Mann-Kendall | Self-implemented, with exact p-values for small n. `pymannkendall`, `scipy.stats.kendalltau` and `statsmodels` are test oracles only. | The statistical core is a research contribution and must be defensible line by line. |
| R4 | Oversized element name | Detector id `OversizedElement`. | "God Component" is object-oriented vocabulary and weakens the architecture-agnostic claim. |
| R5 | Hub name | Detector id `HubLikeElement`. | Keeps v2 tests and examples. |
| R6 | Oversized rule | Robust z (median/MAD) above 3.5. The IQR fence stays for hubs. | Robust to the skewed size distributions of real systems. |
| R7 | Rename matching | Classical features first: name similarity, neighbour Jaccard, size ratio, Hungarian assignment. | Embeddings only if the alignment check shows names are the weak point. |
| R8 | RAG dependencies | Optional extra `rag`. | Keeps PyTorch out of the MVP install. |
| R9 | Change points (`ruptures`) | Kept, post-PP1, optional extra `cp`. | MVP M4 is Mann-Kendall, Sen's slope and Benjamini-Hochberg. |
| R10 | Layered tier, Sinkhole | Post-PP1, only if C1/C2 supply `layer` and `delegation`. | Depends on inputs not yet agreed. |
| R11 | Big Ball of Mud | System-scope instance. Degradation is decided by trends on `largest_scc_share` (up) and `modularity` (down). Modularity uses `greedy_modularity_communities`. | Louvain is randomised; the greedy algorithm is deterministic. |
| R12 | Cycle counting | SCC-based measures (`scc_count`, `largest_scc_size`, `cyclic_edge_count`). Bounded enumeration only for report examples. | Enumerating all simple cycles is exponential. |
| R13 | Package layout | v3 module names: `ingestion`, `detection`, `tracking`, `trends`, `reasoning`, `events`, `review`. | See the amendments below for where they live in this repository. |

## Amendments for this repository (agreed 2026-10-13)

The plan was written for a standalone `src/c3/` package with a SQLite store. C3 is built inside
the team backend, so the team placement contract ([INSTRUCTIONS.md §7](../../INSTRUCTIONS.md))
decides where files go, and the plan decides behaviour.

| Topic | Plan | Here |
|---|---|---|
| Package root | `src/c3/` | `backend/app/components/degradation_detection/`; R13 names are its subcomponents |
| Boundary contracts | `src/c3/contracts/` | `backend/app/domain/` |
| Ports and adapters | `ports/`, `adapters/sqlite/` | component `ports.py`; adapters under `backend/app/infrastructure/postgres/` |
| Store | One SQLite file, SQL migrations | PostgreSQL through SQLAlchemy and Alembic; in-memory fakes in unit tests |
| CLI | `src/c3/cli.py` | `backend/scripts/c3.py` |
| Research config | `configs/` at the root | `backend/configs/`; loader in the component's `config.py` |
| Generated schemas | `schemas/` at the root | `backend/schemas/` |
| Evaluation script | `evaluation/mvp_eval.py` | `backend/scripts/mvp_eval.py` |
| Build and commands | hatchling, Python 3.11+, `make` | uv project on Python 3.13; `backend/scripts/check.ps1` |

## Consequences

- C2 must agree to `ReleasePackageV1.1` and C4 to `DegradationEventV2` before the tags
  `contracts-v1.1.0` and `events-v2.0.0` are created.
- JSON Schemas are generated from the Pydantic models and never edited by hand.
- A guard test fails if runtime code imports a statistical oracle library.
- `ARCHITECTURE.md` §4.2 and §4.3 list the R13 subcomponent names for `degradation_detection`.
