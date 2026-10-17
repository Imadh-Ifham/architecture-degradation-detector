# C3 Implementation Plan v3.1 — Anti-Pattern Degradation Detection

**Project:** J26-SE-332 · Detection of Architecture Degradation in Maintenance-Phase Software Systems (SLIIT IT4010)
**Component:** C3 — Degradation Detection across releases · Owner: Jayawardhana J.M.T.Y (IT23307858)
**Supervisor:** Mr. Vishan Jayasinghearachchi
**Version:** 3.1 · 13 Oct 2026
**Purpose of this file:** the single working plan for building C3 with Claude Code. Put it in the repo at `docs/implementation-plan.md`. `CLAUDE.md` points here.

**Built from (do not regenerate these, reconcile with them):**
- *C3 Technical Approach & Architecture v2* (style-agnostic core, pluggable catalog, M7 audit trail).
- *C3 Implementation Guide & Data Contracts* (v2 reference: ports-and-adapters design, self-implemented Mann-Kendall with exact p-values, Benjamini-Hochberg, decision register D-01…D-21, config YAML, M1–M7 pseudocode, 30 business rules).
- Contracts package (`ReleasePackageV1`, `DegradationEventV1`, `AuditEntryV1`, internal domain models, 30 contract tests, severity guardrail test).
- M1 / M2 / M3 implementation walkthroughs (content-hash idempotency, confidence gate, runtime timeline, metric registry, relative thresholds, Hungarian alignment, lineages).
- *C3 Implementation Plan v3* (supervisor pivot: smells → architectural anti-patterns, detectors as fitness functions, instance tracking with Jaccard, lifecycle labels, BH, catalogue tiers, v3 repo scaffold).

---

## 0. How to read this plan

| Part | What it covers |
|---|---|
| 1 | Locked decisions and the v2 → v3 reconciliation (read before writing any code) |
| 2 | Architecture: modules, package layout, storage, data flow |
| 3 | Data contracts (input, output, internal) |
| 4 | Module specifications M1–M7 (M1–M4 in full detail; M5–M7 for later) |
| 5 | Configuration defaults |
| 6 | **PP1 MVP plan (M1–M4)** — scope, day-by-day tasks, acceptance criteria, demo |
| 7 | Post-PP1 plan (M5–M7 and extensions) |
| 8 | Evaluation plan (every claim → ground truth → metric) |
| 9 | Testing strategy |
| 10 | Decision register (v2 decisions kept + new v3 decisions) |
| 11 | Risks and open questions |
| 12 | How to drive this with Claude Code (session prompts) |

Task IDs (`T-xx`) are the unit of work for Claude Code. Each has: files, tests to write first, acceptance criteria.

---

## 1. Locked decisions and v2 → v3 reconciliation

### 1.1 Locked (never change without the owner saying so)

1. **Pipeline:** C1 Extraction (Imadh) → C2 Validation (Aman) → **C3 Degradation Detection** → C4 Severity Ranking (Weerasuriya). C3 never extracts, validates, or ranks.
2. **Core statistics:** Mann-Kendall trend test + Sen's slope across releases. No fixed metric thresholds decide degradation; a trend does.
3. **Reasoning:** RAG with a prompted LLM only. Never trained or fine-tuned.
4. **No deep learning / custom neural networks anywhere.** (Using a pretrained, frozen embedding model for retrieval in M5 is allowed; nothing is trained.)
5. **Architecture-agnostic:** one generic core; style-specific knowledge only in the detector catalog, selected by `architecture_style`.
6. **No severity in C3 output:** no `severity`, `priority`, `rank`, `impact`, `blast_radius`, `hotspot`, `risk` fields. C4 owns those.
7. **Every claim has a named ground truth and a metric** (Section 8).

### 1.2 The supervisor pivot (v3)

C3 now detects **architectural anti-patterns** (named, usually multi-element bad structures) per release, tracks each **instance** across releases, and tests whether it is getting worse. Each detector is an automated **fitness function** over the validated graph (*Fundamentals of Software Architecture*, Compliance). Chapter 19's decision anti-patterns (Covering Your Assets, Groundhog Day, Email-Driven Architecture) are out of scope: not code-detectable, and ADR analysis is C2's job.

### 1.3 Reconciliation table (v2 vs v3 conflicts — resolved here)

| # | Topic | v2 said | v3 said | **v3.1 decision** |
|---|---|---|---|---|
| R1 | Input field names | `ReleasePackageV1`: `system_id`, `release_id`, `released_at`, `elements[{id,name,kind,size,size_unit,aliases,metrics,extra}]`, `dependencies[{from,to,types,count}]`, `intent[]`, `validation_confidence`, `provenance` | Scaffold schema: `release`, `release_date`, `dependencies[{source,target,type}]`, `datastore_access`, `delegation`, `layer` | **Keep v2 names** (contracts + 30 tests already exist). Add v3 fields as **optional**: `elements[].layer`, top-level `datastore_access[]`, top-level `delegation[]`. Bump to `ReleasePackageV1.1` (minor, backward compatible). Regenerate `schemas/*.json` from Pydantic; never hand-edit. |
| R2 | Output event | `DegradationEventV1` with `smell_type`, element/lineage scoped | `anti_pattern_type`, `instance_id`, `members`, `lifecycle`, `p_adjusted` | **`DegradationEventV2`** (`schema_version: 2.0.0`, major bump): `smell_type` → `anti_pattern_type`; add `scope` (`ELEMENT`/`INSTANCE`/`SYSTEM`), `instance_id`, `members`, `lifecycle`. Keep v2 names `q_value` (not `p_adjusted`), `event_key`, `window`, `affected_metrics`, `context`, `review_status`, `provenance`. [Agree with C4] |
| R3 | Mann-Kendall implementation | Self-implemented (decision log 25.08.2026); exact p for small n; libraries only as test oracles | Tech stack listed `pymannkendall` as a runtime dependency | **Self-implemented.** `pymannkendall`, `scipy.stats.kendalltau`, `statsmodels.multipletests` are **dev-only oracles** in tests. |
| R4 | Oversized element name | `OversizedElement` (not "God class" — OO-specific, breaks agnostic claim) | "God Component" | **`OversizedElement`** is the detector id. Docs may say "Oversized Element (a.k.a. God Component)". |
| R5 | Hub naming | `HubLikeElement` | "Hub-Like Dependency" | **`HubLikeElement`** id (keeps v2 tests/examples). |
| R6 | Oversized rule | Robust z (median/MAD) `size_rz > 3.5` | IQR size outlier | **Robust z > 3.5** (v2). IQR rule stays for Hub-Like. |
| R7 | M3 similarity matching | Plan text mentioned sentence-transformers | — | **Classical features first** (rapidfuzz name + neighbour Jaccard + size ratio, Hungarian). Embeddings only if the alignment check shows names are the weak point. |
| R8 | RAG dependencies | Runtime deps | Runtime deps | **Optional extra `[rag]`** so the MVP install is light (sentence-transformers pulls PyTorch). |
| R9 | Change-point detection (`ruptures`) | In M4 | Not mentioned | **Kept, post-PP1** (optional extra `[cp]`). MVP M4 = MK + Sen + BH. |
| R10 | Sinkhole / layered tier | Layered catalog in v2 | Stretch goal | **Could** (post-PP1, only if C1/C2 supply `layer`/`delegation`). |
| R11 | Big Ball of Mud | — | Largest SCC share high **and** modularity low | Detected as a **system-scope** instance; degradation decided by MK on `largest_scc_share` (↑) and `modularity` (↓), not by the presence threshold. Modularity via deterministic `greedy_modularity_communities` (not Louvain, which is randomised). |
| R12 | Cycle counting | — | "Number of cycles" | **Do not enumerate all simple cycles** (exponential). Use SCC-based measures: `scc_count`, `largest_scc_size`, `cyclic_edge_count`. Bounded enumeration (`length_bound`) only for reporting examples. |
| R13 | Package layout | `m1_ingestion/`, `ports/`, `adapters/` | v3 scaffold: `ingestion/`, `detection/`, `tracking/`, `trends/`, `reasoning/`, `events/`, `review/` | **Use the v3 scaffold layout**, add `ports/` and `adapters/` packages for ports-and-adapters. |

---

## 2. Architecture

### 2.1 C4 model summary

- **Context:** C3 receives validated release packages (from C2, built on C1's extraction) and emits degradation events to C4. A human architect reviews events (M7, post-PP1).
- **Container:** one Python codebase (`c3` package) with a CLI (`typer`). A small FastAPI service is optional, post-PP1. One SQLite file is the store.
- **Component:** M1–M7 below, wired by ports (Python `Protocol`s) so domain logic never touches SQLite or an LLM directly — the same interface/DI pattern used in C#.

### 2.2 Pipeline

```
C2 packages (JSON, one per release)
  └─ M1 Ingestion & Combination ── validate · normalise · gate · persist · timeline
       └─ M2 Anti-Pattern Detection Engine ── per release: graph · metrics · detectors (fitness functions)
            └─ M3 Cross-Release Aligner ── element lineages · instance tracks · lifecycle · series (3 levels)
                 └─ M4 Trend Analyzer ── Mann-Kendall · Sen's slope · Benjamini-Hochberg · candidates
                      └─ M5 Contextual Reasoner (RAG) ── GENUINE / INTENTIONAL / UNCERTAIN + grounded context
                           └─ M6 Event Emitter ── DegradationEventV2 (review_status = PENDING)
                                └─ M7 Architect Review & Audit Trail ── verdict · append-only hash-chained log
                                     └─ C4 (ranking, outside C3)
PP1 MVP = M1 → M4, plus a thin export of M4 candidates as DegradationEventV2 JSON with context.stage = DISABLED.
```

`context.enabled = false` (M5 off) is not a hack — it **is** the trend-only ablation baseline. Build it first, keep it forever.

### 2.3 Package layout (target)

```
src/c3/
  cli.py                     # typer: stub, ingest, run, detect, track, trends, report, baseline, (later) explain, emit, review
  config.py                  # YAML → pydantic C3Config (extra="forbid"), config_hash
  logging.py                 # structlog/JSON logging, reason codes
  contracts/                 # BOUNDARY models (tolerant reader: unknown fields ignored + logged)
    release_package.py       # ReleasePackageV1(.1)
    degradation_event.py     # DegradationEventV2
    audit_entry.py           # AuditEntryV1 (post-PP1 use)
    export_schemas.py        # writes schemas/*.json from the models
  domain/                    # INTERNAL models (extra="forbid"), pure, no I/O
    enums.py                 # ArchitectureStyle, ElementKind, GateStatus, Worsening, Scope, Lifecycle, ContextTag, ContextStage, ReviewStatus, Verdict, TrendKind, TestMethod
    release.py               # CanonicalRelease, ElementSnapshot, DependencyEdge, IntentEntry, DatastoreAccess, Delegation
    graph.py                 # ArchGraph (wraps nx.DiGraph, read-only accessors)
    metrics.py               # MetricDef, MetricObservation
    anti_pattern.py          # AntiPatternInstance, InstanceTrack
    lineage.py               # Lineage, LineageEvent
    series.py                # SeriesPoint, Series (scope, subject_id, metric)
    trend.py                 # MKResult, TrendResult, EventCandidate
  ports/                     # Protocols
    release_repo.py  analysis_repo.py  event_repo.py  clock.py  (later) llm_client.py  retriever.py  audit_repo.py
  adapters/
    sqlite/                  # migrations/*.sql, repo implementations
    memory/                  # in-memory fakes for unit tests
    files/                   # JSON/CSV/plot writers
  ingestion/                 # M1: service.py, normalise.py, gate.py, hashing.py, ordering.py
  detection/                 # M2: graph_builder.py, metric_registry.py, metrics.py, thresholds.py, base.py, registry.py
    universal/               # cyclic_dependency, hub_like_element, unstable_dependency, oversized_element, big_ball_of_mud
    microservices/           # shared_persistence, service_size_outlier (cyclic service dep = universal cyclic at service granularity)
    layered/                 # layer_back_call, architecture_sinkhole (Could)
  tracking/                  # M3: element_alignment.py, similarity.py, lineage.py, instance_matching.py, lifecycle.py, series_builder.py
  trends/                    # M4: mann_kendall.py, exact_dist.py, sens_slope.py, multiple_testing.py, analyzer.py, candidates.py, (later) change_points.py
  reasoning/                 # M5 (post-PP1)
  events/                    # M6: emitter.py (PP1: export-only), event_key.py
  review/                    # M7 (post-PP1)
  baselines/                 # static_threshold.py (PP1 comparison)
  stub/                      # synthetic C2 package generator + ground-truth manifest
evaluation/                  # experiment scripts (PP1: mvp_eval.py)
schemas/                     # generated JSON Schemas (never hand-edited)
configs/default.yaml  configs/catalog.yaml
tests/unit/... tests/contract/ tests/integration/ tests/fixtures/{graphs,series,contracts,stub}
docs/implementation-plan.md (this file)  docs/adr/  docs/architecture/
```

### 2.4 Storage (SQLite, stdlib `sqlite3`, SQL migrations)

| Table | Key | Purpose | Module |
|---|---|---|---|
| `system` | `system_id` | systems seen | M1 |
| `release` | (`system_id`,`release_id`) | `released_at`, `architecture_style`, `granularity`, `validation_confidence`, `gate_status`, `package_hash`, `raw_json`, `ingested_at` | M1 |
| `element_snapshot` | (`system_id`,`release_id`,`element_id`) | name, kind, size, size_unit, aliases (json), layer, metrics (json), extra (json) | M1 |
| `dependency_edge` | (`system_id`,`release_id`,`from_id`,`to_id`) | types (json), count | M1 |
| `datastore_access` / `delegation` | per release | optional v3 inputs | M1 |
| `intent_entry` | `intent_id` | stored now, used by M5 later; `first_seen_release`, `last_seen_release` | M1 |
| `analysis_run` | `run_id` | config, `config_hash`, code/lib versions, status, summary counts | all |
| `metric_observation` | (`run_id`,`release_id`,`element_id`,`metric`) | long/EAV format; `value` nullable | M2 |
| `system_observation` | (`run_id`,`release_id`,`metric`) | system-level measures | M2 |
| `ap_instance`, `ap_member` | (`run_id`,`release_id`,`local_instance_id`) | detector output: type, catalog, scope, measures (json), members | M2 |
| `lineage`, `lineage_member`, `lineage_event` | `lineage_id` | element identity through time; RENAME/SPLIT/MERGE | M3 |
| `instance_track`, `instance_track_member` | `instance_id` (`AP-<TYPE>-NNNN`) | instance identity through time + lifecycle | M3 |
| `series_point` | (`run_id`,`scope`,`subject_id`,`metric`,`ordinal`) | `release_id`, `value` (null stays null) | M3 |
| `trend_result` | (`run_id`,`scope`,`subject_id`,`metric`) | n, s, var_s, z, tau, p, q, method, sen_slope, intercept, worsening, significant | M4 |
| `event_candidate` | (`run_id`,`event_key`) | scope, subject, type, window, trend ids | M4 |
| `degradation_event` | `event_id` | canonical payload; immutable (UPDATE trigger blocks) | M6 |
| `audit_entry` | `seq`/`audit_id` | append-only + hash chain (triggers) | M7 |
| `outbox`, `llm_cache`, `context_assessment` | | post-PP1 | M5–M7 |

---

## 3. Data contracts

### 3.1 Input — `ReleasePackageV1.1` (C2 → C3, one JSON per release)

File naming in the drop folder: `<system_id>__<release_id>.json`.

```json
{
  "schema_version": "1.1.0",
  "system_id": "shopfront",
  "release_id": "v1.4.0",
  "released_at": "2025-04-01T00:00:00Z",
  "architecture_style": "microservices",
  "granularity": "service",
  "elements": [
    {"id": "order-service", "name": "order-service", "kind": "service", "size": 12450, "size_unit": "loc",
     "aliases": ["order-svc"], "layer": null, "metrics": {"lcom": 0.42}, "extra": {}}
  ],
  "dependencies": [
    {"from": "order-service", "to": "payment-service", "types": ["call"], "count": 3}
  ],
  "datastore_access": [ {"element": "order-service", "datastore": "orders_db", "mode": "readwrite"} ],
  "delegation": null,
  "intent": [
    {"intent_id": "ADR-021", "element": "payment-service", "source_type": "adr", "ref": "ADR-021",
     "decision": "split fraud-check out of payment-service", "decision_kind": "split", "date": "2025-03-20"}
  ],
  "validation_confidence": 0.83,
  "provenance": {"c1_model_ref": "c1://shopfront/v1.4.0", "c2_validation_ref": "c2://shopfront/v1.4.0"}
}
```

Rules (from v2 business rules, keep the numbering in code comments):
- `architecture_style` ∈ {`monolith`,`microservices`,`layered`,`event-driven`,`generic`}; default `generic`.
- `elements` ≥ 1; element ids unique; every dependency endpoint must exist (no dangling); self-loops dropped with a log; duplicate edges collapse with `count` summed.
- `adr_ref` accepted as a deprecated alias of `ref`.
- **Tolerant reader:** unknown fields → ignored, logged `UNKNOWN_FIELD_IGNORED`. `extra="forbid"` is for internal models and config only.
- v3 optional fields: missing ⇒ detectors that need them are skipped and logged `CATALOG_INPUT_MISSING`; the pipeline never fails because of them.

### 3.2 Output — `DegradationEventV2` (C3 → C4)

```json
{
  "schema_version": "2.0.0",
  "event_id": "DEG-01J...",
  "event_key": "sha256:5b0c...",
  "supersedes_event_id": null,
  "run_id": "RUN-01J...",
  "system_id": "shopfront",
  "scope": "INSTANCE",
  "anti_pattern_type": "CyclicDependency",
  "catalog": "universal",
  "architecture_style": "microservices",
  "instance_id": "AP-CYC-0007",
  "members": ["order-service", "payment-service", "inventory-service", "shipping-service"],
  "element_id": null,
  "lineage_id": null,
  "lifecycle": "growing",
  "window": {"start_release": "v1.1.0", "end_release": "v1.9.0", "n_releases": 9,
             "low_confidence_releases": ["v1.6.0"]},
  "affected_metrics": [
    {"metric": "member_count", "unit": "elements", "worsening": "INCREASE", "n": 9,
     "s": 30, "tau": 0.83, "p_value": 0.0012, "q_value": 0.0081, "test_method": "EXACT",
     "sen_slope": 0.33, "time_axis": "ordinal", "series": [{"release_id": "v1.1.0", "value": 3}]}
  ],
  "trend_strength": 0.83,
  "context": {"tag": "GENUINE", "stage": "DISABLED", "rule_id": "R0_CONTEXT_DISABLED",
              "justification": null, "retrieved": [], "cited": []},
  "review_status": "PENDING",
  "provenance": {"c1_model_refs": ["..."], "c2_validation_refs": ["..."],
                 "release_package_hashes": ["sha256:..."], "config_hash": "sha256:..."}
}
```

- `scope=ELEMENT` ⇒ `element_id`, `lineage_id` set; `instance_id` may be set if the element's instance exists. `scope=SYSTEM` ⇒ `subject` is the system; `members` may list the largest SCC.
- `trend_strength = max |tau|` — documented as **evidence strength, not severity**.
- `event_key = sha256(canonical_json({system_id, scope, subject_id, anti_pattern_type, catalog, start_release}))` — end release excluded on purpose so a continuing trend is the same event [D-18].
- Illustrative numbers above are placeholders, not results.
- **Guardrail test:** the generated schema must contain no property matching `/(severity|priority|rank|impact|blast|hotspot|risk)/i`.

### 3.3 Audit entry — `AuditEntryV1` (post-PP1, M7)

`audit_id`, `seq`, `event_id`, `event_key`, `verdict` (`CONFIRMED`/`REJECTED`/`NEEDS_INVESTIGATION`), `reviewer_id` (pseudonymous), `note` (required for REJECTED / NEEDS_INVESTIGATION, ≥10 chars) [D-19], `timestamp` (UTC `Z`), `evidence_snapshot_ref` (sha256 of the canonical event payload shown), `prev_hash`, `entry_hash`.

### 3.4 Contract versioning

- Schemas are generated from Pydantic (`c3 schemas export`). A snapshot test fails if a model changes without regenerating.
- Breaking change ⇒ major bump. Fields tagged [Agree with C2]/[Agree with C4] need teammate sign-off before tagging `contracts-v1.1.0` / `events-v2.0.0`.

---

## 4. Module specifications

### M1 — Ingestion & Combination (PP1: full)

**Responsibility:** the only door into C3. Turn each C2 package into generic, style-tagged rows; later modules never see raw JSON.

Flow: `Receive → Validate → Normalise → Idempotency → Gate → Persist (1 transaction) → (Outbox, post-PP1)`; timeline is a query computed at the start of every run.

1. **Receive:** `c3 ingest <file|dir>`; files `<system_id>__<release_id>.json`; size cap `ingest.max_package_bytes`.
2. **Validate:** `ReleasePackageV1.model_validate(...)`. Shape error → `INPUT_SCHEMA_INVALID`. Semantic errors → own codes (`DUPLICATE_ELEMENT_ID`, `DANGLING_DEPENDENCY`, …). A rejected package never touches the store.
3. **Normalise (pure):** to `CanonicalRelease` of `ElementSnapshot`, `DependencyEdge`, `IntentEntry`, `DatastoreAccess`, `Delegation`. Defaults: `name ← id`, `kind ← granularity`. C1 metrics prefixed `c1.`. Collapse duplicate edges, drop self-loops.
4. **Idempotency:** `package_hash = sha256(canonical_json(payload))` (sorted keys, fixed float digits). Same (system, release, hash) → no-op. Same key, different hash → `RELEASE_CONFLICT` (reject; explicit `--replace` later).
5. **Quality gate (pure):** `c ≥ 0.70 → ACCEPTED`; `0.50 ≤ c < 0.70 → DOWNWEIGHTED` (included, listed on events); `c < 0.50 → EXCLUDED` (stored, not in timeline) [D-07]. Boundaries: 0.70 is ACCEPTED, 0.50 is DOWNWEIGHTED.
6. **Persist:** one transaction per package.
7. **Timeline (pure query):** order by `released_at` (never by tag name — `v1.10` vs `v1.9`), tie-break by semver then id; filter to the main release line via `ingest.release_line_regex` (back-ports excluded) [D-06]; exclude `EXCLUDED`. Ordinal assigned at runtime, never stored as identity.
8. **Intent dedup:** same intent across packages → one row with `first_seen_release`/`last_seen_release`.
9. **Granularity/style drift:** log a warning when `granularity` or `architecture_style` changes between releases.

**Tests first:** one per rejection reason (invalid fixtures); gate boundaries; normalisation (duplicate edge → count 2, self-loop dropped, missing name → id); idempotency no-op and conflict; ordering (equal timestamps, non-semver tags, back-port); intent dedup; excluded releases stored but not in timeline; unknown field logged not rejected.

### M2 — Anti-Pattern Detection Engine (PP1: universal tier + registry; microservice tier partly)

**Responsibility:** per release, build the graph, compute registry-declared metrics, run detector plugins (fitness functions), emit anti-pattern instances and system measures.

**Step 1 — Graph:** `nx.DiGraph`; one node per element (isolated nodes included), edges with `types`, `weight=count`. Trust M1's canonical data.

**Step 2 — Metric registry.** Every metric declared once with its *worsening direction* (M4 needs it).

| Metric | Level | Definition | Worse when |
|---|---|---|---|
| `fan_in`, `fan_out` | element | distinct in/out neighbours | ↑ |
| `fan_in_norm`, `fan_out_norm` | element | ÷ (N−1) — **primary for cross-style** [D-04] | ↑ |
| `instability` | element | fan_out/(fan_in+fan_out); **null when isolated** (0/0) | supports detectors only |
| `size`, `size_rz` | element | size; robust z = (size − median)/(1.4826·MAD) within release; **null when MAD = 0** | ↑ |
| `scc_size` | element | size of its SCC (1 if none) | ↑ |
| `unstable_dep_ratio` | element | share of e's out-deps pointing to elements with higher instability | ↑ |
| `c1.*` | element | pass-through from C1, direction from config [D-21] | config |
| `scc_count`, `largest_scc_size`, `largest_scc_share`, `cyclic_edge_count` | system | SCCs of size ≥ 2 | ↑ |
| `modularity` | system | Newman modularity of `greedy_modularity_communities` on the undirected graph | **↓** |
| `ap_count.<Type>` | system | number of instances of each type | ↑ |
| `ap_involvement_share` | system | share of elements in ≥1 instance | ↑ |

Storage is long format (`release, element, metric, value`), so adding a metric never changes the schema.

**Step 3 — Detectors (fitness functions).** Interface:

```python
class AntiPatternDetector(Protocol):
    id: str                          # "CyclicDependency"
    catalog: str                     # "universal" | "microservices" | "layered"
    styles: frozenset[str]           # {"*"} or {"microservices"}
    scope: Scope                     # ELEMENT | INSTANCE | SYSTEM
    required_fields: frozenset[str]  # e.g. {"datastore_access"}
    driving_metrics: tuple[str, ...] # metrics whose worsening trend maps to this anti-pattern
    instance_measures: tuple[str, ...]  # per-instance series M3 builds (e.g. "member_count")
    def detect(self, g: ArchGraph, ctx: ReleaseContext) -> list[AntiPatternInstance]: ...
```

All thresholds are **relative to the release's own distribution**, from config, never constants in code.

| Tier | Detector id | Instance = | Present when | Driving metrics / instance measures | MVP |
|---|---|---|---|---|---|
| Universal | `CyclicDependency` | one SCC of size ≥ 2 | Tarjan SCC (`nx.strongly_connected_components`) | `scc_size`; instance: `member_count`, `internal_edge_count` | **Must** |
| Universal | `HubLikeElement` | one element | fan_in **and** fan_out > Q3 + 1.5·IQR of the release | `fan_in_norm`, `fan_out_norm`; instance: `degree` | **Must** |
| Universal | `UnstableDependency` | one element + its bad edges | `unstable_dep_ratio ≥ 0.3` (Martin SDP) | `unstable_dep_ratio`; instance: `bad_edge_count` | **Must** |
| Universal | `OversizedElement` | one element | `size_rz > 3.5` | `size_rz`; instance: `size_rz` | **Must** |
| Universal | `BigBallOfMud` | the system (members = largest SCC) | `largest_scc_share ≥ 0.25` **and** `modularity ≤ 0.30` (pre-declared, configurable) | system: `largest_scc_share` ↑, `modularity` ↓ | **Must** |
| Microservices | `CyclicServiceDependency` | — | universal `CyclicDependency` when `granularity = service` (reported with catalog `microservices` label, no duplicate detector) | as Cyclic | Must (free) |
| Microservices | `SharedPersistence` | one datastore + its services | ≥ 2 services access the same datastore | instance: `services_per_store` | **Should** (needs `datastore_access`) |
| Microservices | `MegaService` / `NanoService` | one service | size_rz > 3.5 / < −3.5 | `size_rz` | Could |
| Layered | `LayerBackCall` | one violating edge set per layer pair | edge from lower to higher layer | instance: `violating_edge_count` | Could (needs `layer`) |
| Layered | `ArchitectureSinkhole` | the system | share of pass-through delegations | system: `sinkhole_ratio` | Could (needs `delegation`) |

**Step 4 — Registry (the ONLY style branch in C3):**

```python
def detectors_for(style: str, available_fields: set[str]) -> list[AntiPatternDetector]:
    chosen = [d for d in ALL if "*" in d.styles or style in d.styles]
    runnable = [d for d in chosen if d.required_fields <= available_fields]
    for d in set(chosen) - set(runnable):
        log.info("detector_skipped", reason="CATALOG_INPUT_MISSING", detector=d.id)
    return runnable
```

`configs/catalog.yaml` lists which detectors are enabled per style. An **architecture-agnostic guard test** fails if any module outside `detection/registry.py` (and contracts/domain enums, ingestion pass-through) branches on `architecture_style`. A **registry extension test** registers a dummy style + dummy detector and asserts all existing tests still pass.

**Tests first:** golden fixture graphs — one planted anti-pattern each (3-node cycle, star hub with 6 in/6 out, unstable chain, one giant element, two services on one DB, mud graph) **plus negatives** (DAG, balanced graph) where every detector returns nothing; isolated node → `instability = null`; MAD = 0 → `size_rz = null`; missing `datastore_access` → SharedPersistence skipped, universal still runs; modularity deterministic across runs.

### M3 — Cross-Release Aligner (PP1: exact + alias + rename; instance tracking; series)

**Rule: when unsure, break the series rather than guess** (a wrong join invents a trend with a real p-value).

**Element alignment (consecutive releases):**
1. **Exact pass:** same `id`; then through `aliases` (previous id supplied by C1/C2 — cheapest, most reliable rename signal).
2. **Similarity pass** for leftovers (disappeared × new): `sim = 0.4·name + 0.4·neighbour_jaccard + 0.2·size_ratio`. Name = `rapidfuzz` token-set ratio on names split on camelCase/`-`/`_`/`.`; neighbour overlap via already-aligned ids; size ratio = min/max. One-to-one via `scipy.optimize.linear_sum_assignment` (Hungarian). Accept if `sim ≥ 0.75` **and** runner-up ≥ 0.05 lower; else `ALIGNMENT_AMBIGUOUS`, no link.
3. **Splits/merges (post-PP1):** a disappeared element scoring ≥ 0.5 against ≥ 2 new ones whose combined neighbours overlap the original → `SPLIT`; mirror → `MERGE`.
4. **Lineage** `LIN-…`: continues through renames; through split/merge via the largest successor (others start new lineages recording origin); **never crosses a change of `element_kind`**. Events stored in `lineage_event` (M5 uses them later as evidence).

**Instance tracking (v3):**
1. Map each instance's members to **lineage ids** first (so renames don't break instance identity).
2. Per anti-pattern type, between consecutive releases, build a Jaccard matrix `|A∩B| / |A∪B|`; one-to-one with Hungarian; link if `≥ 0.5` [D-22]. Single-element instances (Hub, Oversized) reduce to lineage matching. System-scope instances (BigBallOfMud) are a single track per system.
3. Unlinked instance in release r → new track `AP-<TYPE>-NNNN` (`introduced` at r). Track with no successor → `resolved` at r+1.
4. **Lifecycle at the end of the window** (Sas, Avgeriou & Uyumaz 2022): `introduced` (age = 1 release), `growing` (instance measure has a significant worsening trend from M4), `persistent` (present, no significant growth), `resolved` (absent in last release). Per-transition labels (`introduced/grew/shrank/persisted/resolved`) are also stored for reporting.

**Series builder (the M3 deliverable — one table, three scopes):**

| Scope | Subject | Metrics |
|---|---|---|
| `ELEMENT` | lineage | element metrics from the registry |
| `INSTANCE` | instance track | detector `instance_measures` (e.g. `member_count`) |
| `SYSTEM` | system | system metrics + `ap_count.<Type>` + `ap_involvement_share` |

`SeriesPoint(ordinal, release_id, value)` — **null stays null, never 0**. Series start when the subject first exists. Style-specific series only over contiguous same-style releases.

**Tests first:** planted rename linked; alias rename linked; ambiguous pair not linked; kind change breaks lineage; instance survives a member rename; growing cycle stays one track; a cycle that disappears is `resolved`; two unrelated cycles never merge; series lengths match the stub manifest.

### M4 — Trend Analyzer (PP1: full core; change points later)

**Mann-Kendall (self-implemented, `trends/mann_kendall.py`):**
- `S = Σ_{i<j} sign(x_j − x_i)`; `tau = S / (n(n−1)/2)` (Kendall tau-a; report tau-b too if ties).
- **n < `exact_below` (10), no ties:** exact two-sided p from the Mahonian (inversion-count) distribution (DP, `lru_cache`).
- **n < 10 with ties:** permutation test (`n_perm = 20000`, fixed seed), `p = (hits+1)/(n_perm+1)`.
- **n ≥ 10:** normal approximation with **tie-corrected variance** and continuity correction.
- Constant series → `DEGENERATE`, p = 1.
- Two-sided p reported; worsening decided by sign vs the metric's direction [D-01].
- Sanity values: n=5 strictly increasing → S=10, p = 2/120 ≈ 0.0167; n=4 increasing → p ≈ 0.083 (can never reach 0.05).

**Sen's slope (`trends/sens_slope.py`):** median of pairwise slopes `(x_j − x_i)/(t_j − t_i)` with an **explicit time axis** (`ordinal` = per included release [D-05]); intercept = median(x) − slope·median(t). Never let a library re-index missing points (compresses time, inflates slope).

**Benjamini-Hochberg (`trends/multiple_testing.py`):** q-values over **all series tested in one system run** (one family, pre-declared). Gate on `q ≤ α` (0.05), report both p and q [D-02].

**Minimum length:** skip series with fewer than `min_releases = 8` non-null points → `SERIES_TOO_SHORT`; report tested/untested counts [D-03].

**Analyzer → candidates (`trends/analyzer.py`, `trends/candidates.py`):**
1. Test every series of every scope; store every `trend_result` (significant or not).
2. BH across the run; mark `is_worsening` (direction from registry) and `is_significant`.
3. **Candidate assembly:**
   - `INSTANCE`: an instance-measure trend significant + worsening, and the instance present in the last release → candidate typed by the instance's anti-pattern.
   - `ELEMENT`: a lineage metric trend significant + worsening, mapped through detectors' `driving_metrics` to an anti-pattern **present for that element in at least the last release of the window** → candidate of that type. Significant worsening trends not covered by any present anti-pattern → one `MetricDrift` candidate per lineage [D-09].
   - `SYSTEM`: system series significant + worsening → candidate typed by the series' anti-pattern (`largest_scc_share`/`modularity` → `BigBallOfMud` if present in last release, else `MetricDrift`; `ap_count.X` → X).
   - Window = span of the tested series; list `DOWNWEIGHTED` releases inside it; compute `event_key`, `trend_strength`.
4. **Change points (post-PP1):** `ruptures` PELT, penalty `penalty_c · σ̂² · log n`, `min_size 2`; `trend_kind ∈ {GRADUAL_DRIFT, STEP_CHANGE}`.
5. **Sensitivity (post-PP1):** Hamed-Rao modified MK for serial correlation; report how many events survive [D-11].

**Tests first (in order):** `sum(mahonian(n)) == n!` for n ≤ 10 + symmetry; MK known series (n=5, n=4, constant, alternating); oracle agreement — tie-free vs `scipy.stats.kendalltau(np.arange(n), x, method="exact")`, n ≥ 10 with ties vs `pymannkendall.original_test`; Sen recovers planted slope on `x = 3 + 0.8t` and survives one outlier; non-increasing time raises; BH hand example, q monotone with p, q ≥ p, agrees with `statsmodels.multipletests(method="fdr_bh")`; Hypothesis properties (reverse negates S; adding constant / positive scaling leaves S, tau, p unchanged and scales Sen's slope; strictly monotone transform leaves tau unchanged); candidate assembly truth tables. Optional: `mutmut` on `trends/`.

### M5 — Contextual Reasoner (post-PP1)

Classifies each candidate: `GENUINE` (degradation), `INTENTIONAL` (documented deliberate change), `UNCERTAIN`, with grounded context explaining *why*. No severity.

- **Stage 1 — rule layer (no LLM):** `R0_CONTEXT_DISABLED` (`context.enabled=false` → GENUINE, stage DISABLED; this is the ablation baseline); `R1_NO_INTENT_EVIDENCE` (no intent linked to any lineage id/system within [window start − `buffer_days` (90), window end] **and** best retrieval score < `min_score` → GENUINE, stage DEFAULT — conservative fallback); `R2_DOCUMENTED_RESTRUCTURE` (SPLIT/MERGE in window **and** linked intent within ±buffer with `decision_kind` ∈ {split, merge, extract, restructure} → INTENTIONAL, stage RULE; needs `decision_kind` from C2). Each rule is a truth-table unit test. Report the **rule-layer resolution rate**.
- **Stage 2 — retrieval:** corpus = C2 intent entries (ADRs, design docs, release notes, refactoring commits, issues/PRs) + (outside eval mode) architect verdicts from M7 as `source_type=architect_verdict`. Chunk ≈ 280 tokens, overlap 50; keep `intent_id, source_type, ref, date, element, passage_id`. **Filter then rank:** metadata filter (element ∈ lineage/instance member ids or null; date in buffered window) → cosine similarity with a frozen, revision-pinned sentence-transformer (e.g. `all-MiniLM-L6-v2`), optional BM25 fusion (RRF) [D-13]; top_k 6, score ≥ 0.35. Query text built from the candidate (`"order-service (formerly order-svc): CyclicDependency instance AP-CYC-0007 growing, member_count +0.33/release, v1.1.0..v1.9.0"`).
- **Stage 3 — prompted reasoning:** pinned model, temperature 0, `prompt_version` recorded; JSON output `{tag, justification ≤600 chars, cited: [{passage_id, quote}]}`. **Grounding check:** every quote must appear verbatim in its passage; INTENTIONAL with no verified quote → downgraded to UNCERTAIN/GENUINE (flagged). Provider failure → GENUINE + flag (or fail run when `strict=true` in eval) [D-14].
- **Determinism:** `llm_cache` with `record`/`replay` modes; all re-analysis in replay. Providers: `anthropic` | `openai_compatible` | `replay` behind an `LLMClient` Protocol [D-12]; unit tests use a stub.
- **Evaluation leakage:** `eval.mode=true` excludes `architect_verdict` passages (or temporal split) [D-16].

### M6 — Event Emitter (PP1: export only; full post-PP1)

PP1: serialise M4 candidates to `DegradationEventV2` JSON (`context.stage=DISABLED`, `review_status=PENDING`), validate against the generated schema, write `out/<run_id>/events.json`.
Post-PP1: persist immutable rows (UPDATE trigger blocks), `supersedes_event_id` when the same `event_key` reappears with a longer window, outbox message `c3.event.emitted`, export endpoint/file for C4.

### M7 — Architect Review & Audit Trail (post-PP1)

- **Review queue:** CLI (`c3 review`) listing `PENDING` events with evidence (anti-pattern, members, series, trend stats, context, cited quotes). Optional minimal FastAPI form.
- **Verdict:** `CONFIRMED` / `REJECTED` / `NEEDS_INVESTIGATION`; note required for the last two [D-19].
- **Audit log:** append-only SQLite table — INSERT only, UPDATE/DELETE blocked by triggers; **hash chain** `entry_hash = sha256(prev_hash ‖ canonical_entry)`; `evidence_snapshot_ref` = hash of the payload shown; `c3 audit verify` recomputes the chain. Latest entry by `seq` defines `review_status`. Superseded events start PENDING and link to prior history.
- **Forward to C4:** reviewed events carry `review_status` + `review` summary.
- **Feedback to M5:** export CONFIRMED/REJECTED with notes as retrieval corpus (excluded in eval mode).
- Review is asynchronous; never blocks new runs.

---

## 5. Configuration (`configs/default.yaml`)

```yaml
schema_version: "1.1.0"
store: {path: "data/c3.sqlite"}
ingest:
  release_line_regex: "^v?\\d+\\.\\d+\\.\\d+$"     # [D-06]
  max_package_bytes: 20000000
gate: {accept: 0.70, exclude: 0.50}                  # [D-07] [Agree with C2]
metrics:
  normalised_coupling: true                          # [D-04]
  c1_passthrough: [{name: "c1.lcom", unit: "lcom", worsening: "INCREASE"}]   # [D-21]
detection:
  hub: {iqr_k: 1.5}
  unstable: {ratio: 0.3}
  oversized: {z_max: 3.5}
  big_ball_of_mud: {largest_scc_share_min: 0.25, modularity_max: 0.30}      # [D-24]
  modularity: {algorithm: "greedy"}                                          # [D-27]
align:
  weights: {name: 0.4, neighbours: 0.4, size: 0.2}
  rename_min: 0.75
  ambiguity_margin: 0.05
  part_min: 0.5
  split_min: 0.5
tracking: {instance_jaccard_min: 0.5}                # [D-22]
trend:
  alpha: 0.05
  gate_on: "q"                                       # [D-02]
  sidedness: "two-sided"                             # [D-01]
  min_releases: 8                                    # [D-03]
  exact_below: 10
  n_perm: 20000
  seed: 20261013
  time_axis: "ordinal"                               # [D-05]
  bh_family: "run"                                   # [D-26]
cp: {enabled: false, penalty_c: 2.0, min_size: 2}    # post-PP1
context: {enabled: false, buffer_days: 90, strict: false}   # false = trend-only baseline (MVP)
retrieval: {mode: "dense", embedding_model: "sentence-transformers/all-MiniLM-L6-v2",
            embedding_revision: "<pin>", chunk_tokens: 280, chunk_overlap: 50, top_k: 6, min_score: 0.35}
llm: {provider: "anthropic", model: "<pinned>", temperature: 0.0, max_tokens: 600,
      prompt_version: "classify_v1", cache_mode: "record", timeout_s: 60, max_retries: 3, max_calls_per_run: 500}
review: {note_required_for: ["REJECTED", "NEEDS_INVESTIGATION"], note_min_chars: 10}   # [D-19]
eval: {mode: false}                                  # [D-16]
```

Rules: `C3Config` uses `extra="forbid"` (typo fails at start-up). Every number-changing parameter is part of `config_hash` stored on each run. **Freeze the config before running evaluation systems**; tune only on stub data or a pilot system; record the frozen hash in the thesis appendix.

---

## 6. PP1 MVP plan (M1–M4)

### 6.1 Scope

**MVP goal (one sentence for the supervisor):** "Given a series of validated release packages, C3 detects architectural anti-patterns in every release, tracks each anti-pattern instance and element across releases, and uses Mann-Kendall, Sen's slope and Benjamini-Hochberg to report only the ones that are statistically getting worse — as C4-ready events."

| In MVP (PP1) | Deferred (after PP1) |
|---|---|
| Contracts V1.1 in / V2 out, schema export, contract + guardrail tests | REST API, outbox |
| M1 full (validate, normalise, gate, idempotency, SQLite, timeline) | `--replace` re-ingest |
| M2 graph, metric registry, 5 universal detectors, registry + agnostic guard | Microservice tier beyond Cyclic/SharedPersistence; layered tier |
| SharedPersistence (if time — stub provides `datastore_access`) | Mega/Nano service |
| M3 exact + alias + similarity rename (Hungarian), lineages, instance tracking + lifecycle, 3-scope series | Splits/merges |
| M4 self-implemented MK (exact/permutation/normal), Sen, BH, candidates | Change points, Hamed-Rao sensitivity |
| Thin M6 export to `DegradationEventV2` JSON (context DISABLED) | M5, full M6, M7 |
| Synthetic stub system with planted ground truth; static-threshold baseline; MVP evaluation report | Real systems, Arcan/Designite comparison, RAGAS, ablation |

### 6.2 Day-by-day (assumes ~4 focused hours/day; PP1 early next week — shift days if PP1 is earlier)

| Day | Date | Tasks | End-of-day proof |
|---|---|---|---|
| 1 | Wed 14 Oct | T-00, T-01, T-02 | `pytest` green on contracts; schemas generated |
| 2 | Thu 15 Oct | T-03, T-04 | `c3 stub generate` + `c3 ingest` → 10 releases stored, 1 rejected, 1 downweighted |
| 3 | Fri 16 Oct | T-05, T-06, T-07 | `c3 detect` → per-release instance counts match manifest |
| 4 | Sat 17 Oct | T-08, T-09, T-10 | `series.csv` with ELEMENT/INSTANCE/SYSTEM series |
| 5 | Sun 18 Oct | T-11, T-12 | `c3 trends` → planted trends significant, flat/noisy not |
| 6 | Mon 19 Oct | T-13, T-14 | `c3 run` end-to-end + `mvp_eval` report |
| 7 | Tue 20 Oct | T-15 | Clean-clone demo rehearsal, README, slides |

**Cut lines if behind (in this order):** drop SharedPersistence → drop similarity rename (keep exact + alias; stub uses aliases) → plots become CSV only → drop static baseline comparison. Never cut: M4 oracle tests, golden fixtures, contract guardrail.

### 6.3 Tasks

#### T-00 — Repo reconcile / scaffold
- If the v3 scaffold already exists: align it to Section 2.3 (add `contracts/`, `ports/`, `adapters/`, `baselines/`, `stub/`; move RAG deps to `[rag]` extra; `pymannkendall`, `statsmodels`, `hypothesis` to `[dev]`; add `rapidfuzz`, `pyyaml`, `matplotlib`, `structlog`). If empty: create it.
- If the earlier contracts zip is available locally, import its models/tests into `src/c3/contracts` and `src/c3/domain` instead of rewriting.
- `pyproject.toml` (hatchling, Python ≥3.11), ruff (line 100), mypy strict on `src/c3`, pytest markers `integration`, `llm`, `slow`; GitHub Actions CI (ruff, mypy, pytest excluding integration/llm).
- `docs/adr/0002-anti-patterns-over-code-smells.md`, `docs/adr/0003-v2-v3-contract-reconciliation.md` (Section 1.3).
- **Accept:** `ruff`, `mypy`, `pytest` all pass on a clean venv.

#### T-01 — Contracts and domain models
- `ReleasePackageV1.1` (tolerant reader), `DegradationEventV2`, `AuditEntryV1`; internal domain models (`extra="forbid"`), enums.
- `c3 schemas export` → `schemas/c3_input.schema.json`, `schemas/c3_output.schema.json`, `schemas/c3_audit.schema.json`.
- **Tests first:** valid/invalid fixtures in `tests/fixtures/contracts/`; semantic rules (duplicate ids, dangling deps, unknown field ignored+logged, `adr_ref` alias); schema snapshot test; **severity guardrail test**; event example validates against generated schema.
- **Accept:** all contract tests green; schemas regenerate identically.

#### T-02 — Config and logging
- `config.py` loads YAML → `C3Config` (extra forbid), computes `config_hash` (canonical JSON sha256). Structured JSON logs with `reason` codes.
- **Tests:** typo key fails; hash stable; hash changes when alpha changes.

#### T-03 — Synthetic stub system + ground truth
`c3 stub generate --out data/samples/shopfront --seed 20261013` writes 10 `ReleasePackageV1.1` files (v1.0.0 … v1.9.0, monthly, `microservices`, `service` granularity, ~12–15 services) plus `ground_truth.yaml`. Planted scenarios:

| ID | Scenario | Expected |
|---|---|---|
| S1 | Cycle {order, payment, inventory} appears at v1.1.0; absorbs `shipping` at v1.4.0 and `notification` at v1.7.0 | INSTANCE event `CyclicDependency`, lifecycle `growing`; SYSTEM `cyclic_edge_count` ↑ |
| S2 | `catalog` fan-in and fan-out grow each release | ELEMENT event `HubLikeElement` |
| S3 | `legacy-auth` very high but **flat** fan-in | **No event** (static baseline flags it → shows why trends beat thresholds) |
| S4 | `order-svc` renamed `order-service` at v1.4.0 (alias provided) | One continuous lineage; S1 instance unbroken |
| S5 | `reporting` size grows faster than the system | ELEMENT event `OversizedElement` |
| S6 | `search` metrics random walk, no trend | **No event** |
| S7 | `gateway` gains dependencies on less stable services | ELEMENT event `UnstableDependency` |
| S8 | `largest_scc_share` rises, `modularity` falls | SYSTEM series significant (BigBallOfMud if threshold met by v1.9.0, else `MetricDrift`) |
| S9 | Two services share `orders_db` from v1.2.0, a third joins later | INSTANCE `SharedPersistence` (if T-07 done) |
| S10 | `v1.5.0` confidence 0.60 | DOWNWEIGHTED, listed in event windows |
| S11 | Extra package `v1.3.1-hotfix` with a dangling dependency | Rejected `DANGLING_DEPENDENCY`; also not on main line |

Also generate **pure series fixtures** (`tests/fixtures/series/`): rising (planted Sen slope 0.8), flat, noisy-no-trend, step, with ties, short (n=5,7).
- **Accept:** generator deterministic (same seed → byte-identical files); manifest lists expected events **and expected non-events**.

#### T-04 — M1 Ingestion
As Section 4/M1. `IngestService(repo: ReleaseRepo, clock, cfg)`; pure `normalise`, `gate`, `ordering.timeline`; SQLite adapter + migration `001_init.sql`; in-memory fake repo for unit tests.
- **Accept:** all M1 tests; `c3 ingest data/samples/shopfront` → 10 accepted/downweighted, 1 rejected, printed summary; re-run is a no-op.

#### T-05 — M2 graph + metric registry
`graph_builder.py`, `metric_registry.py` (MetricDef: name, level, unit, worsening), `metrics.py` computing element + system metrics, persisted to `metric_observation` / `system_observation`.
- **Accept:** fixture tests (scc_size, null instability, null size_rz, modularity determinism).

#### T-06 — Universal detectors + thresholds
`thresholds.py` (IQR fence, robust z helpers), five universal detectors per Section 4/M2, each with ≥1 positive and ≥1 negative golden fixture in `tests/fixtures/graphs/<detector>__positive_NN.json` / `__negative_NN.json`.
- **Accept:** each detector finds exactly the planted instance and nothing else; all negatives empty.

#### T-07 — Registry, catalog, style guard (+ SharedPersistence)
`registry.py`, `configs/catalog.yaml`, agnostic guard test, registry extension test, skip-with-log behaviour. If time: `SharedPersistence`.
- **Accept:** `c3 detect --system shopfront` → per-release instance table matching manifest.

#### T-08 — M3 element alignment + lineages
Exact, alias, similarity (rapidfuzz + neighbour Jaccard + size ratio, Hungarian, 0.75 / 0.05 margin), lineages, `lineage_event` (RENAME). Splits/merges stubbed `NotImplementedError` with xfail tests.
- **Accept:** S4 rename linked; ambiguity fixture not linked; kind change breaks lineage; `alignment_sample.csv` exported.

#### T-09 — Instance tracking + lifecycle
Member → lineage mapping, per-type Jaccard + Hungarian (≥ 0.5), track ids, transition labels, end-of-window lifecycle (the `growing` label is finalised after M4 results).
- **Accept:** S1 is one track through the rename; resolved/introduced fixtures pass.

#### T-10 — Series builder
Three scopes into `series_point`; nulls preserved; export `out/<run>/series.csv`.
- **Accept:** series counts/lengths match the manifest.

#### T-11 — M4 statistical core
`exact_dist.py`, `mann_kendall.py`, `sens_slope.py`, `multiple_testing.py` + all M4 tests in Section 4/M4 (oracles are dev deps).
- **Accept:** all oracle and property tests green; coverage of `trends/` ≥ 95%.

#### T-12 — Analyzer, candidates, event export (thin M6)
`analyzer.py` (skip short series, test, BH, worsening, significance), `candidates.py` (three scopes, MetricDrift, window, low-confidence releases, `event_key`, `trend_strength`), `events/emitter.py` export-only → `events.json` validated against `DegradationEventV2`.
- **Accept:** on the stub: S1, S2, S5, S7 (+S8, S9) produce events; S3, S6 produce none; every event validates; guardrail holds.

#### T-13 — Orchestration, report, static baseline
`c3 run --system shopfront` = M2→M3→M4→export under one `analysis_run` (config hash, code/lib versions, timings, counts by reason code). `c3 report` → `out/<run>/report.md` (run summary, per-release anti-pattern counts, top events, tested/untested series counts) + PNG plots for event series with the Sen line. `c3 baseline --static` → flags elements over fixed thresholds at the last release (e.g. fan_in > 10, size > 10k) for comparison.
- **Accept:** one command reproduces everything from an empty DB.

#### T-14 — MVP evaluation script
`evaluation/mvp_eval.py` compares outputs to `ground_truth.yaml`:
- trend detection precision/recall/F1 (expected events vs non-events);
- Sen slope absolute error on planted-slope series;
- MK p-value agreement with oracles (max |Δp|);
- detector golden-fixture pass rate;
- instance/lineage matching accuracy vs planted links;
- static-threshold baseline vs C3 on S3/S6 (false positives avoided).
Writes `out/<run>/mvp_eval.md`.
- **Accept:** report generated; numbers honest (no tuning on the evaluation output — the stub is a development fixture, say so).

#### T-15 — Demo hardening
README (install, `make demo`), `make demo` = clean DB → stub → ingest → run → report → eval. Fresh-clone test. Tag `v0.1.0-pp1`.

### 6.4 MVP definition of done

- [ ] `make demo` runs from a fresh clone in < 2 minutes.
- [ ] `ruff`, `mypy --strict`, `pytest` green in CI; coverage ≥ 85% overall, ≥ 95% on `trends/`.
- [ ] Planted worsening scenarios flagged; flat/noisy ones not; S3 contrast with static baseline shown.
- [ ] Events validate against `DegradationEventV2`; no severity fields.
- [ ] Rename (S4) doesn't break any series or instance.
- [ ] Run is reproducible: same config hash → same events.

### 6.5 PP1 demo script (≈10 minutes)

1. **Problem + design (1 min):** one slide with the M1–M7 pipeline; MVP = M1–M4 highlighted; C1/C2/C4 boundaries.
2. **Ingest (1 min):** `c3 ingest` — show gate summary (accepted / downweighted / rejected with reason code).
3. **Detect (2 min):** per-release anti-pattern table; show the cycle growing across releases; explain detectors as fitness functions and relative thresholds.
4. **Track (1 min):** the rename at v1.4.0 and the cycle as one instance track.
5. **Trends (3 min):** plot of `member_count` with Sen line; MK p and BH q; then `legacy-auth` — static threshold flags it, C3 doesn't, because it isn't getting worse. This is the core research claim.
6. **Output (1 min):** one event JSON for C4 — no severity, C4 ranks.
7. **Quality (1 min):** test counts, oracle agreement, golden fixtures, MVP eval table.
8. **Next (30 s):** M5 RAG reasoning, M6/M7 review + audit trail, real systems, full evaluation.

---

## 7. Post-PP1 plan (M5–M7 and extensions)

Two-week sprints from PP1; dates set after PP1 feedback.

| Sprint | Focus | Tasks | Exit criterion |
|---|---|---|---|
| P1 | Complete M2/M3/M4 | Splits/merges (T-20); microservice tier: SharedPersistence (if not done), Mega/Nano (T-21); change points via `ruptures` PELT + `trend_kind` (T-22); Hamed-Rao sensitivity (T-23); real-system ingest from C1/C2 or hand-converted OSS with ≥ 10 releases (T-24) | Real system series + events produced |
| P2 | M5 rule layer + retrieval | Intent corpus from stored `intent_entry`; R0–R2 truth-table tests (T-30); chunking, metadata filter, frozen embeddings, Chroma/FAISS index, optional BM25 (T-31) | Retrieval returns linked passages on stub ADRs |
| P3 | M5 prompted reasoning | `LLMClient` Protocol + Anthropic adapter + replay adapter + cache (T-32); prompt `classify_v1`, JSON parsing, verbatim-quote grounding check, fallbacks (T-33); eval mode exclusion (T-34) | Stub candidates tagged with grounded context; replay deterministic |
| P4 | M6 full + M7 | Immutable event persistence, supersession, outbox (T-40); review CLI, verdicts, note rule (T-41); append-only audit with triggers + hash chain + `c3 audit verify` (T-42); verdict export to M5 corpus (T-43); optional FastAPI review form/API (T-44) | Tampering with an audit row is detected |
| P5 | Integration | Contract sign-off with Aman (C2) and Weerasuriya (C4); tag contracts; end-to-end with real C2 output; C4 consumes events (T-50) | C4 reads C3 events without adapters |
| P6 | Evaluation + thesis | Section 8 experiments; layered tier only if ahead (T-60…T-66) | All Section 8 metrics reported |

---

## 8. Evaluation plan (claim → ground truth → metric)

| Claim | Ground truth | Metric | When |
|---|---|---|---|
| Statistical core is correct | scipy exact Kendall, pyMannKendall, statsmodels BH; planted slopes | max abs p difference; Sen slope recovery error; mutation score (optional) | PP1 |
| Detectors find anti-patterns correctly | Golden fixtures; anti-patterns **injected by controlled graph mutation** into real release graphs; manually validated stratified sample | Precision, recall, F1 per detector | PP1 (fixtures) / P6 |
| Detectors agree with established tools | Arcan or Designite on the Java/monolith subject | Cohen's kappa; instance overlap | P6 |
| Flagged trends are genuine | Planted trends (stub); manual check of flagged instances against release history | Precision/recall of flagged trends; BH-adjusted q; events surviving Hamed-Rao | PP1 (stub) / P6 |
| Trend detection beats static thresholds | Stub S3/S6 + real-system manual labels | False-positive reduction vs static-threshold baseline | PP1 / P6 |
| Identity tracking is reliable | Planted renames (stub); hand-labelled element and instance links on a real subset | Alignment accuracy (SO1); instance matching accuracy | PP1 / P6 |
| Architecture-agnostic | Same pipeline on ≥ 1 microservice and ≥ 1 monolith/layered system, each ≥ 10 releases | F1 per style; universal vs style tier contribution | P6 |
| RAG explanations are grounded | Retrieved passages | RAGAS faithfulness, context precision; verbatim-quote verification rate | P6 |
| Context layer adds value | Labels from a broader evidence base (commits, issues) | **Ablation:** trend-only vs trend+context, McNemar's test; rule-layer resolution rate | P6 |
| Architect agrees with C3 | M7 verdicts (eval mode, no verdict leakage) | Agreement rate, Cohen's kappa between verdicts and M5 tags | P6 |

Rules: freeze config before evaluation runs; tune on stub/pilot only; report tested vs untested series counts; report minimum releases as a stated constraint.

---

## 9. Testing strategy

- **Pyramid:** pure-function unit tests (most), contract tests, a few SQLite integration tests, one end-to-end stub run (`integration` marker).
- **TDD loop per task:** write/un-xfail tests → implement → refactor → ruff/mypy/pytest → commit `feat(T-xx): …`.
- **Golden fixture graphs** (positive + negative per detector), **series fixtures** (rising/flat/noisy/step/ties/short), **contract fixtures** (valid/invalid).
- **Oracles** for M4 (dev deps only). **Property-based** tests (Hypothesis) for MK/Sen/BH invariants.
- **Architecture tests:** agnostic guard (style branching only in registry); domain has no I/O imports; severity guardrail on the output schema.
- **LLM isolation (post-PP1):** stub client in unit tests; real calls only under `llm` marker; replay mode for evaluation.
- **Determinism:** fixed seeds; modularity algorithm deterministic; canonical JSON hashing with fixed float precision.

---

## 10. Decision register

v2 decisions kept (IDs from the v2 implementation guide; others there remain valid):

| ID | Decision | Default |
|---|---|---|
| D-01 | MK sidedness (**pre-declare**) | Two-sided p, then filter by worsening direction |
| D-02 | Significance gate (**pre-declare**, confirm with supervisor) | Gate on BH q ≤ 0.05; report p and q |
| D-03 | Minimum series length (**pre-declare**) | 8, exact test below 10 (fills the proposal §3.2.1 placeholder) |
| D-04 | Primary coupling metrics (**pre-declare**) | Normalised (÷ N−1) primary for cross-style; raw also reported |
| D-05 | Sen time axis | Ordinal (per included release); days as secondary |
| D-06 | Release line | Main line only via regex |
| D-07 | Confidence gate | ≥0.70 accept, 0.50–0.70 downweight (include + list), <0.50 exclude |
| D-09 | Uncovered significant trends | One `MetricDrift` candidate per subject |
| D-11 | Serial correlation | No correction by default; Hamed-Rao sensitivity analysis reported |
| D-12 | LLM provider | `anthropic` / `openai_compatible` / `replay` behind a Protocol |
| D-13 | Retrieval mode | Dense; hybrid BM25 optional |
| D-14 | Provider failure | GENUINE + flag; `strict` fails the run in eval |
| D-16 | Evaluation leakage | Eval mode excludes architect verdicts from retrieval |
| D-18 | Event identity | `event_key` excludes end release |
| D-19 | Review notes | Required for REJECTED / NEEDS_INVESTIGATION |
| D-21 | C1 pass-through metrics | Declared in config with worsening direction |

New in v3.1:

| ID | Decision | Default and reason |
|---|---|---|
| D-22 | Instance matching | Jaccard ≥ 0.5 on lineage-mapped members, Hungarian one-to-one |
| D-23 | Oversized naming | `OversizedElement` (style-neutral) |
| D-24 | Big Ball of Mud presence (**pre-declare**) | largest SCC share ≥ 0.25 and modularity ≤ 0.30; degradation decided by trend, not this threshold |
| D-25 | Contract reconciliation | v2 names kept; v3 fields optional (Input V1.1); Output V2 major bump |
| D-26 | BH family (**pre-declare**) | All series tested in one system run |
| D-27 | Modularity algorithm | `greedy_modularity_communities` (deterministic) |
| D-28 | MVP context | `context.enabled=false` (trend-only baseline) for PP1 |
| D-29 | Cycle measures | SCC-based; no unbounded simple-cycle enumeration |

---

## 11. Risks and open questions

| Risk | Impact | Mitigation |
|---|---|---|
| Real C1/C2 output not ready for PP1 | No real-system demo | Synthetic stub with planted ground truth is the PP1 dataset; state it plainly |
| C1/C2 can't supply `datastore_access`, `layer`, `delegation`, `aliases`, `decision_kind` | Style tiers, alias renames, R2 rule unavailable | All optional; detectors skip + log; similarity rename fallback; R2 falls through to RAG |
| Too few releases | MK lacks power | Subjects with ≥ 10 releases; min 8 enforced; report untested counts |
| Many series → false positives | Spurious events | BH; M7 review |
| Wrong alignment joins | Invented trends | Break-not-guess rule; ambiguity margin; manual alignment sample |
| Growth confound (everything's fan-in rises) | Healthy elements flagged | Normalised metrics primary; relative `size_rz` |
| Arcan/Designite only Java/C# | Tool comparison on one style only | Use on the monolith subject; mutation injection elsewhere |
| LLM non-determinism | Irreproducible results | Temperature 0, pinned model, record/replay cache |
| PP1 time pressure | Incomplete MVP | Cut lines in 6.2; Claude Code per-task sessions |

**Open questions (bring to supervisor / team):**
- [ ] Supervisor: confirm "anti-patterns" = structural ones (cycles, hubs, Big Ball of Mud, Sinkhole), not Ch. 19 decision anti-patterns.
- [ ] Supervisor: gate on BH q (D-02) and minimum 8 releases (D-03).
- [ ] Supervisor: universal tier + microservices; layered tier a stretch goal.
- [ ] Imadh (C1): `size`, `aliases`, `datastore_access`, call-level `delegation` available?
- [ ] Aman (C2): `layer` per element, `decision_kind` on intent, confidence gate values, Input V1.1 sign-off.
- [ ] Weerasuriya (C4): `DegradationEventV2` (scope, instance_id, members, lifecycle) sufficient for ranking.

---

## 12. Driving this with Claude Code

### 12.1 Setup
1. Save this file as `docs/implementation-plan.md` in the repo.
2. Make sure `CLAUDE.md` says: "The implementation plan is `docs/implementation-plan.md`. Work one task ID at a time. Section 1 decisions are locked."
3. One task (or two small ones) per Claude Code session. Use plan mode for T-04, T-06, T-08, T-11, T-12.
4. After each session: review the diff, run `make check`, commit.

### 12.2 CLAUDE.md additions

```
## Working rules
- Plan: docs/implementation-plan.md. Implement only the task ID you are given.
- Locked: Section 1 of the plan (C3 boundaries, no deep learning, prompted RAG only, architecture-agnostic, no severity fields, self-implemented MK/Sen/BH).
- TDD: write the task's "tests first" list, see them fail, implement, refactor.
- Thresholds come from configs/default.yaml and are relative to each release's distribution. Never hard-code numbers in detectors.
- Only detection/registry.py may branch on architecture_style.
- Domain models: extra="forbid". Contract (boundary) models: tolerant reader.
- Never let null become 0 in metrics or series.
- Commands: make install | make check (ruff + mypy + pytest) | make demo
- If a contract field conflicts with the plan, stop and ask; don't invent fields.
- Commit per task: "feat(T-xx): <summary>". Don't push.
```

### 12.3 Session prompt template

```
Read CLAUDE.md and docs/implementation-plan.md (Sections 1, 2, 3 and the spec for this task).
Implement task T-xx exactly as specified in Section 6.3 (module details in Section 4).
1. Show me a short plan (files to create/change, tests to write) before editing.
2. Write the "tests first" list; run them and confirm they fail for the right reason.
3. Implement until they pass. Keep domain code pure; I/O only in adapters.
4. Run make check (ruff, mypy --strict, pytest). Fix everything.
5. Summarise: what was built, test count, anything assumed or deferred, and the acceptance criteria status.
6. Commit "feat(T-xx): ...". Do not push.
```

### 12.4 Day 1 kickoff prompt

```
Read docs/implementation-plan.md fully, then CLAUDE.md.
Do T-00 then T-01 then T-02 from Section 6.3.
For T-00: inspect the repo first. If the v3 scaffold exists, reconcile it with Section 2.3 and the
dependency changes listed in T-00 rather than recreating it. Write ADR 0003 from Section 1.3.
For T-01: implement ReleasePackageV1.1 (tolerant reader), DegradationEventV2 and AuditEntryV1 per
Section 3, internal domain models with extra="forbid", the schema export command, and all listed
tests including the severity guardrail and schema snapshot test.
For T-02: config loader with config_hash.
Follow the session template steps 1-6 for each task, committing after each one.
```
