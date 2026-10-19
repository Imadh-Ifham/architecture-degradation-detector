# C4-ADR-007 — Consume C3's DegradationEventV2 and the release package C3 analysed

- **Status:** Accepted (owner, 2026-10-18). Assumptions A1–A5 are provisional until the
  teammate confirmations listed against each one.
- **Date:** 2026-10-18
- **Task:** C4-T05 Contracts

## Context

CLAUDE.md §4.1 described a C3 event "contract v1" and told C4 to mirror it locally
if C3 had not published one. C3 has published one: `DegradationEventV2`
(`schema_version 2.0.0`) in `backend/app/domain/degradation_event.py`, with a generated
schema in `backend/schemas/c3_output.schema.json`. Its shape differs from v1: it is
scoped (`ELEMENT` / `INSTANCE` / `SYSTEM`), carries per-metric series instead of one
count, and has no `graph_ref`, `paths`, `releases_present`, `first_seen_release`,
`adr_refs`, `c3_confidence` or `evidence_refs`.

A read of the teammates' code and plans (2026-10-18) found:

- C3 analyses `ReleasePackageV1.1` (`app/domain/release_package.py`), stored as a
  `CanonicalRelease` in PostgreSQL. Aman's `ValidatedArchitectureGraph`
  (`app/domain/validated_architecture.py`) is a different document and nothing in C3
  reads it yet.
- C3's plan (`docs/implementation-plan.md` §2.2, §M6) fixes the PP1 export as
  `review_status = PENDING` and `context.stage = DISABLED` (so `context.tag = GENUINE`)
  for every event. `CONFIRMED` arrives only after PP1, from C3's review queue (M7), and
  `supersedes_event_id` is post-PP1 too.
- C3's plan line 733 lists "C4: `DegradationEventV2` sufficient for ranking" as an open
  sign-off, so contract-change requests are expected now.
- C1's inventory attributes every source file to a component (`files[].component_id`),
  but C2's translation keeps only manifest paths, and neither C2 document passes paths on.
- The PP1 demo system (Online Boutique) has no ADRs, per the C2 plan.

## Decision

1. **No local mirror.** C4 validates payloads with `app.domain.degradation_event.
   DegradationEventV2` directly. C4 does not edit that file. Missing fields are
   contract-change requests to C3, never inferred silently.
2. **Field mapping** (CLAUDE.md §4.1 keeps the full table):
   `system` → `system_id` · `degradation_type` → `anti_pattern_type` ·
   `detected_release` → `window.end_release` · `elements[].id` → `element_id`
   (ELEMENT) or `members` (INSTANCE) · `intentionality` → `context.tag`.
3. **Ingestion rules** (implemented in C4-T08):
   - payload fails `DegradationEventV2` validation → quarantine `malformed_payload`;
   - `review_status == REJECTED` → always skip `rejected`, whatever the switch below
     (C3, 2026-10-18);
   - `scoring_rank_only_confirmed` defaults to **false** while C3 emits only `PENDING`;
     every record shows its `review_status`. Switch back to true once C3's M7 sets
     `CONFIRMED`;
   - `context.tag == INTENTIONAL` → skip `intentional`; `UNCERTAIN` → rank and show the
     tag on the record;
   - `scope == SYSTEM` → skip `system_scope_not_rankable` and list it in the report.
     Blast radius of "the whole system" is always 100 %, which would distort the ranking;
   - an event whose `event_id` is named by another event's `supersedes_event_id` → skip
     `superseded` (only the latest version is ranked);
   - `trend_strength`, `q_value` and `tau` are **never** severity inputs. C3 states they
     measure statistical evidence, not severity, and using them would overlap with C3.
   - The same degradation is matched **across runs by `event_key`**, never `event_id`:
     C3's `event_id` contains its `run_id` and changes every run (C3, 2026-10-18). This
     matters for comparing AV-on/off runs, releases, and calibration-frozen reruns.
4. **Graph source.** C4 loads the release package C3 analysed for
   `(system_id, window.end_release)`, not Aman's validated graph. Its element ids are the
   ids C3's events use, so resolution needs no id mapping. Dependencies are `from → to`
   = "from depends on to", which matches CLAUDE.md §4.3. `provenance.c2_validation_refs`
   and `provenance.release_package_hashes` identify and verify the package.
5. **ADR dimension inactive.** No element-level ADR source exists for the demo system,
   so AV stays inactive and the weights renormalise (CLAUDE.md §5.3). That is the
   situation Gate 2 was designed to decide; it is not pre-empted here.
6. **Report additions.** Each `SeverityRecord` carries `anti_pattern_type`, `scope`,
   `review_status` and `context_tag`; the envelope uses `system_id` / `release_id`, and
   lists `skipped` events with a reason (not only counts).

## Provisional assumptions

Status after the teammates' answers of 2026-10-18 (details below the table):

| # | Value C4 needs | Use now | Status | Waits on |
|---|---|---|---|---|
| A1 | first release the anti-pattern was present (hotspot range start, §5.2) | `first_seen_release` when present; else `window.start_release`, flagged `first_seen_fallback=true` | **Stand-in confirmed wrong by C3**: for ELEMENT events the window starts when the element's lineage starts, before the anti-pattern existed. Kept only as a flagged fallback | C3 V2.1.0 `first_seen_release` (proposed, optional; null when the event has no `instance_id`) |
| A2 | releases present (persistence, §5.4) | `instance_history[].release_id` when present; else releases with a non-null `series` value, flagged `presence_fallback=true` | **Overcount confirmed by C3** (ELEMENT series have a value wherever the element exists; meaningless for SYSTEM) | C3 V2.1.0 `instance_history[{release_id, transition, member_count}]` (proposed, optional) |
| A3 | which graph to load (§4.3) | release package for `system_id` + `window.end_release` | **Confirmed by C3.** `element_id`/`members` are the ids at `window.end_release`, after renames. INSTANCE `members` come from the track's last occurrence, which equals `window.end_release` unless the last instance measure is null | — (resolution reports any miss as `unresolved_element`) |
| A4 | element file paths (resolution fallback §5.1, hotspot §5.2) | node attribute `extra.source_paths` when present; otherwise exact-id resolution only; the element is flagged in the hotspot features, and the hotspot dimension is inactive for the run if no element has paths | **Accepted by C2** as a separate pass-through for C4 in M8 (graph publishing, not started); C2's own `source_paths` stays manifest-only. **Caveat:** C1's committed inventory attributes **one** source file per service, so a hotspot over it would be meaningless | C2 M8; C1 to confirm real scans attribute all files of a component |
| A5 | element → decision links (AV, §5.3) | none: **AV inactive for PP1** | **Feasible from C2's edge verdicts** (`bucket`, `governing_decision`, `source_tier`), with caveats below. Adopting it changes §5.3 and is a Gate-2 decision | C2 M6 classification (bucket vocabulary CLS-2 not frozen) and a constructed violating fact |

**A4 correction.** C4's first diagnosis said C2's translation drops the paths. It does
not: `_paths_by_component` keeps only the manifest categories, and those are exactly the
categories where C1 sets `component_id: null`, so it collects nothing (0 of 12 elements
have paths). The filter is deliberate for C2's evidence, hence the separate pass-through.
C2 does not read source code; passing on paths C1 already attributed does not change that.

**A5 caveats (C2, 2026-10-18).**
1. `governing_decision` is **not** an ADR reference: the demo repository has zero
   decision records, and all 25 decisions in force were reconstructed from Kubernetes
   config. The signal is a *recorded-decision violation*; a feature named for ADRs would
   overclaim on such a corpus.
2. Weight by `source_tier`: a contradiction resting on `tier_2_executable_config` is
   weaker evidence than one resting on a written decision record.
3. `bucket = needs_review` is **not** clean: C2 declined to rule on it. It must not be
   counted with `confirmed`.
4. On the demo corpus `contradicted = 0` (20 of 20 governed facts confirmed). An all-zero
   signal there means "nothing to find", not "no violations".
5. `bucket` is an unconstrained string until C2's CLS-2 lands; C4 must not hard-code
   `contradicted` before then.

Dropped, not requested: `c3_confidence` (no formula uses it) and `evidence_refs`
(commits come from C4's own git mining).

## Alternatives considered

- **Keep a PROVISIONAL v1 mirror in `<C4>/models.py`.** Rejected: it would fork a
  contract that already exists and drift from it.
- **Load Aman's `ValidatedArchitectureGraph`.** Rejected for now: different ids from
  C3's events, no file paths, and not the graph C3 detected on.
- **Rank SYSTEM-scope events over their `members`.** C3's plan allows `members` to list
  the largest SCC. Deferred: kept out of PP1 to keep the ranking unambiguous.
- **Wait for C3 to add the missing fields.** Rejected: it blocks Layer 1. The
  stand-ins are visible here and in each run's manifest instead.

## Consequences

- During PP1 every event C3 produces is `PENDING` and `GENUINE`, so C4 ranks all
  ELEMENT- and INSTANCE-scope events.
- Persistence (A2) and hotspot (A1, A4) carry declared threats to validity until C3 and
  C2 confirm; each run's manifest records which stand-ins were used.
- Requests sent; C3 and C2 answered on 2026-10-18 (above). Still open: C3's V2.1.0
  release (needs Thisuri's approval of the fields), C2's M8 path pass-through and M6
  bucket vocabulary, one constructed violating fact shared by C2 and C4 for testing, and
  C1's answers on id stability and per-file attribution. Update this record as each lands.
- If A5 is adopted at Gate 2, the `adr_violation` dimension should be renamed (e.g.
  `decision_violation`) in `SeverityReportV1` with a minor schema bump, so the report does
  not claim ADRs that do not exist.
