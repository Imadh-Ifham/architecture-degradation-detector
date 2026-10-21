# Priorities page (severity ranking) — frontend handoff

For the UI teammate. The ranking lives in the group UI as the **Priorities** page
(`/priorities`, sidebar "results" group, pipeline phase **Score**), built on the skeleton's
shared primitives (`components/ui`), `useRequest` and `lib/api`. The backend part is read-only:
two `GET` endpoints over reports that are already saved on disk. There is no "run" endpoint for
PP1; rankings are made with a script (below).

| File | What |
|---|---|
| `frontend/src/features/priorities/PrioritiesPage.tsx` | the page: ranking picker (`?run=<id>` in the url), provenance banner, stats row, ranked table (severity bar + "made of" bar), selected-row detail, "Not scored" table |
| `frontend/src/features/priorities/RankedEventDetail.tsx` | one event opened: the four parts with value, weight, share of score and raw measurements; "off for this run" for an inactive part |
| `frontend/src/features/priorities/dimensions.ts` | labels, one-line meanings and bar shades of the four parts; provenance and weights wording |
| `frontend/src/lib/api/scoring.ts` | `listScoringRuns()`, `readSeverityReport(runId)`, `ScoringRunSummary`; re-exported from `lib/api` |
| `frontend/src/lib/severityReport.ts` | **generated** TypeScript types of the report (`SeverityReportV1`, `SeverityRecord`, …) |
| `router.tsx`, `layouts/navigation.ts`, `features/reserved/reservedPages.tsx`, `features/pipeline/PipelinePage.tsx` | route points at the page; Priorities and the Score phase marked `ready`; placeholder removed; Score shows "complete" once a ranking is saved |

Restyle freely; please keep the behaviour rules in "What to show" below.

## 1. Get data on your machine (otherwise the page is empty)

The API reads `backend/artifacts/scoring/<system>/<run_id>/` (git-ignored, so empty on a fresh
clone). All commands from `backend/`, PowerShell.

**Option A — no run needed (Online Boutique, 10 seconds).** Copy the two saved T21 runs:

```powershell
$F = "app/components/degradation_scoring/docs/pp1/figures/t21_online_boutique"
New-Item -ItemType Directory -Force artifacts/scoring/online-boutique | Out-Null
Copy-Item -Recurse $F/av_on  artifacts/scoring/online-boutique/t21-ob-av-on
Copy-Item -Recurse $F/av_off artifacts/scoring/online-boutique/t21-ob-av-off
```

**Option B — generate the fixture runs (no database, no repo clone needed).**

```powershell
uv sync
$F = "tests/fixtures/degradation_scoring"
uv run python -m scripts.c4_rank --events $F/events/fixture_events.v1.json `
  --graph $F/graphs/fixture_release_package.v1.5.0.json --adr-index $F/adr --run-id demo-adr-on
uv run python -m scripts.c4_rank --events $F/events/fixture_events.v1.json `
  --graph $F/graphs/fixture_release_package.v1.5.0.json --no-adr --run-id demo-adr-off
```

A run id can be used once; to redo one, delete its folder under `artifacts/scoring/` first.
The fixture runs show more badge cases (UNCERTAIN, path-prefix match, skipped and quarantined
events) than Online Boutique.

**Start both apps**

```powershell
cd backend;  uv run uvicorn app.main:app --reload     # http://127.0.0.1:8000/docs
cd frontend; npm install; npm run dev                  # http://localhost:5173/priorities
```

The Vite dev server proxies `/api/*` to the backend, so no CORS setup is needed. Open a given
ranking directly with `http://localhost:5173/priorities?run=demo-adr-on`.

## 2. Endpoints

| Method + path | Returns | Errors |
|---|---|---|
| `GET /degradation-scoring/runs` | `ScoringRunSummary[]`, newest first; `[]` when nothing is saved | — |
| `GET /degradation-scoring/runs/{run_id}/report` | `SeverityReportV1` (the saved `c4_report.json`) | 404 unknown id · 409 id used by two systems · 422 malformed id · 500 saved file breaks the contract |

Errors come as `{"detail": "..."}`; `api.ts`'s `ApiError` already shows that text.

Example responses (real, from the T21 Online Boutique runs):
- `docs/pp1/frontend/sample_runs.json` — the run list
- `docs/pp1/frontend/sample_report.online_boutique.av_on.json` — a full report (6 events, AV on)

Run list entry:

```json
{
  "run_id": "t21-ob-av-on",
  "system_id": "online-boutique",
  "release_id": "v0.10.7",
  "data_provenance": "fixture-events+live-history",
  "active_dimensions": ["blast_radius", "hotspot", "adr_violation", "persistence"],
  "counts": {"payloads": 6, "ranked": 6, "skipped": 0, "quarantined": 0},
  "resolution_rate": 1.0,
  "created_at": "2026-10-19T16:59:36.074336Z"
}
```

One record of the report (abridged):

```json
{
  "event_id": "DEG-C4OB-T21-0001",
  "anti_pattern_type": "HubLikeElement",
  "scope": "ELEMENT",
  "review_status": "PENDING",
  "context_tag": "GENUINE",
  "rank": 1,
  "severity": 0.5941,
  "dimensions": {
    "blast_radius":  {"raw": 0.595, "normalized": 0.595, "weight": 0.467, "active": true,
                      "features": {"fan_in_ratio": 0.333, "pagerank": 0.175, "betweenness": 0.0, "depth": 1.0}},
    "hotspot":       {"raw": 0.910, "normalized": 0.910, "weight": 0.277, "active": true,
                      "features": {"churn_decayed": 13.4, "authors": 2.0, "coupling": 0.0, "bugfix_ratio": 1.0, "commits": 2.0}},
    "adr_violation": {"raw": 0.0, "normalized": 0.0, "weight": 0.160, "active": true, "features": {"av": 0.0}},
    "persistence":   {"raw": 0.325, "normalized": 0.325, "weight": 0.095, "active": true,
                      "features": {"consecutive_releases": 4.0, "growth_slope": 0.16}}
  },
  "contributions": {"blast_radius": 0.545, "hotspot": 0.448, "adr_violation": 0.0, "persistence": 0.007},
  "resolution": {"status": "exact", "confidence": 1.0},
  "elements": ["productcatalogservice"],
  "explanation": null, "audit": null, "evidence": []
}
```

(Numbers rounded here; see the sample file for exact values.)

## 3. What each field means

**Report envelope**

| Field | Meaning | Show it? |
|---|---|---|
| `run_id`, `system_id`, `release_id` | which run, which system, which release the events were detected at | header |
| `data_provenance` | `live` = real inputs · `fixture` = all hand-made · `fixture-events+live-history` = hand-made events/graph, real git history | **banner when not `live`** |
| `active_dimensions` | criteria used for ranking (AV can be switched off) | header |
| `weights_version`, `weights_provenance` | which AHP weight set; `provisional-author-elicited` = not yet confirmed by the supervisor | header, small |
| `ahp_cr` | AHP consistency ratio of the weights (≤ 0.10 is acceptable) | header, small |
| `normalization`, `normalization_bounds` | how features were scaled to 0–1 (`minmax_small_n` below 10 events) | optional / details |
| `resolution_rate` | share of eligible events whose elements were found in the graph | header |
| `records` | ranked events, rank 1 = most severe (always present, may be empty) | cards |
| `skipped` | valid events not ranked + `reason` (`rejected`, `intentional`, `system_scope_not_rankable`, `superseded`, `not_confirmed`) | small table |
| `quarantined` | unusable payloads + `reason` (`malformed_payload`, `unresolved_element`) + `detail` | small table |

**Record (one card)**

| Field | Meaning |
|---|---|
| `rank` | 1..n, 1 = most severe |
| `severity` | 0–1 TOPSIS closeness: 1 = as bad as possible on every active criterion |
| `elements` | the architecture elements (services) the event concerns, as found in the graph — the main label of a row (schema 1.2.0; empty in older reports, then show `event_id`) |
| `event_id`, `anti_pattern_type`, `scope` | C3's event: id, kind of degradation, `ELEMENT` (one service) or `INSTANCE` (a group) |
| `review_status` | C3's human review state; `PENDING` for every event today |
| `context_tag` | C3's judgement: `GENUINE` or `UNCERTAIN` (intentional ones are skipped) |
| `dimensions.<d>.normalized` | the criterion score 0–1 used for ranking (`raw` is the same number) |
| `dimensions.<d>.weight` | AHP weight of the criterion in this run (active weights sum to 1) |
| `dimensions.<d>.features` | the raw measurements behind the score (details / tooltip) |
| `dimensions.<d>.active` | `false` = criterion off in this run |
| `contributions.<d>` | share of this event's severity coming from the criterion (sum to 1) |
| `resolution.status` | `exact` = element ids matched the graph; `prefix_fallback` = matched by source path (confidence 0.7) |
| `explanation`, `audit`, `evidence` | always `null` / empty for PP1 (explanations come after PP1) |

The four dimensions:

| Key | Label | Plain meaning | Features |
|---|---|---|---|
| `blast_radius` | Blast radius | how much of the system depends on the degraded element | `fan_in_ratio`, `pagerank`, `betweenness`, `depth` |
| `hotspot` | Evolutionary hotspot | how actively and messily the code is changing | `churn_decayed`, `authors`, `coupling`, `bugfix_ratio`, `commits` |
| `adr_violation` | ADR violation | breaks a recorded architecture decision (optional) | `av` (0–1) |
| `persistence` | Persistence | how long it has stayed and how fast it grows | `consecutive_releases`, `growth_slope` |

## 4. What to show on a card

1. **Rank** and **severity** as a number and a horizontal bar (`width = severity × 100 %`).
2. **Four dimension rows**, always in the order blast radius, hotspot, ADR violation,
   persistence: normalised value, weight, contribution (as %). A stacked bar of the
   contributions also works well.
3. **Badges**: `scope`; `review_status`; `UNCERTAIN` when `context_tag == "UNCERTAIN"`;
   "path-prefix match" when `resolution.status == "prefix_fallback"`; "<dimension> off" for each
   inactive dimension.
4. **Fixture banner** on the page whenever `data_provenance !== "live"`: "hand-made inputs, not
   findings". Never hide it — examiners must see which numbers are fixtures.

**Inactive-dimension rule.** A dimension with `active: false` has `weight 0` and contribution
0 by contract. Show it greyed out as **"off"**, never as a score of 0 — a 0 would claim the
event was measured and found harmless. Check `active`, not the value.

## 5. TypeScript types

`frontend/src/lib/severityReport.ts` is generated from the report's JSON Schema
(`backend/app/components/degradation_scoring/docs/schemas/severity_report.schema.json`); do not
edit it. After a contract change, regenerate (needs Node; downloads the generator via npx):

```powershell
cd backend
uv run python -m scripts.scoring_export_schemas          # Pydantic model -> JSON Schema
powershell -ExecutionPolicy Bypass -File scripts/c4_export_ts_types.ps1   # JSON Schema -> TS
```

Optional fields in the generated types (`records?`, `skipped?`, …) are always present in API
responses; the `?` comes from defaults in the schema. `ScoringRunSummary` (run list) is written by
hand in `api.ts` and mirrors `app/api/schemas/degradation_scoring.py`.

## 6. Known gaps (for the team)

- **Two ids for one system.** The workspace names a repository after its clone url
  (`microservices-demo-<hash>`, `build_repository_key`), while rankings (and C2's review queue)
  name the system `online-boutique`. The page therefore picks a ranking loosely (exact id or
  `<system_id>-` prefix, else the newest) and the Score phase is "complete" when any ranking is
  saved. One shared system id across components would let both match exactly.
- **No run button.** Scoring is started from the command line for PP1; the page only reads.

