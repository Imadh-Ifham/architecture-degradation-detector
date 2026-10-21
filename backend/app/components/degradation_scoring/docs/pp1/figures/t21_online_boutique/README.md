# T21 — Online Boutique end-to-end run (AV on vs AV off)

**Fixture events, live history.** The 6 events, the service graph and the two ADRs + links are
hand-made fixtures. Only the commit history is real (Online Boutique, tags v0.10.0–v0.10.7).
`data_provenance: "fixture-events+live-history"`. These rankings are not findings.

| Input | File (under `backend/tests/fixtures/degradation_scoring/`) | Provenance |
|---|---|---|
| Events (6, real services, real v0.10.x tags) | `events/online_boutique_events.v1.json` | fixture |
| Graph (complete call graph: 10 services, 14 gRPC calls, release v0.10.7) | `graphs/online_boutique_graph.v0.10.7.json` | manual fixture |
| Element → paths (`src/<service>/**`, T14) | `mappings/online_boutique.source_paths.v1.json` | manual mapping |
| ADRs + element → ADR links (AV-on run only) | `adr/online_boutique/` | fixture stand-in for C2 (C4-ADR-012) |
| Commit history | `C:\repos\add-repositories\c4-history\microservices-demo` | live |

Folders `av_on/` and `av_off/` hold each run's `c4_report.json`, `c4_report.html`,
`c4_run_manifest.json` and `c4_quarantine.json`, copied unchanged from
`artifacts/scoring/online-boutique/<run_id>/` (the manifest's file hashes still match).

## Rankings

Weights (provisional AHP `ahp_v1`, CR 0.011): AV on BR 0.467 · EH 0.277 · AV 0.160 · PS 0.095;
AV off BR 0.556 · EH 0.330 · PS 0.114 (same ratios, renormalised). 6 ranked, 0 skipped,
0 quarantined, resolution rate 1.0, normalisation `minmax_small_n`, fixed-reference TOPSIS.
`eh_coupling` is 0 for all six events (zero range), so it is left out of the hotspot mean
(C4-ADR-015; marked `zero_range` in the manifest bounds and logged).

| Event | Service(s) | AV | Rank on | Severity on | Rank off | Severity off |
|---|---|---|---|---|---|---|
| E01 HubLikeElement | productcatalogservice | 0 | 1 | 0.594 | 1 | 0.652 |
| E04 InappropriateIntimacy | checkoutservice + cartservice | 0.7 | **2** | 0.529 | **3** | 0.519 |
| E02 UnstableDependency | checkoutservice | 0 | **3** | 0.486 | **2** | 0.524 |
| E05 MetricDrift (UNCERTAIN) | cartservice | 0.7 | 4 | 0.483 | 4 | 0.467 |
| E06 UnstableDependency | emailservice | 1.0 | 5 | 0.407 | 5 | 0.353 |
| E03 OversizedElement | frontend | 0 | 6 | 0.322 | 6 | 0.334 |

## How the ranks change (AV on → AV off)

- **One swap, caused by the ADR link.** E04 (checkout + cart; cart is linked to the accepted
  component-scope ADR-0002, AV 0.7) is 2nd with AV on and 3rd with AV off; E02 (checkout, no
  link) moves the other way, 3rd → 2nd. The other four events keep their ranks.
- **AV changes the order but does not override the other criteria.** E06 has the strongest
  link (accepted system-scope ADR-0001, AV 1.0) and its severity rises 0.353 → 0.407, but it
  stays 5th: emailservice has no source-code commits in its window (hotspot 0) and AV carries
  only 0.160 of the weight. E05 (AV 0.7) also stays 4th, though only 0.003 behind E02.
- **The top and the bottom do not move.** E01 is first in both runs: productcatalogservice is
  called by frontend, checkout and recommendation (largest fan-in, 3 of 9 other services) and
  has the highest hotspot score (0.910: 2 authors, both counted commits are fixes). E03 is last in both because nothing
  depends on frontend, so its blast radius is 0.

## Notes

- Hotspot counts source files only (`scoring_history_include_globs`). Most Online Boutique
  commits in these windows are dependency bumps (`go.mod`, `.csproj`, Dockerfiles), so E04 and
  E06 have 0 counted commits. `unmapped_line_share` = 0.0087 (manifest, `hotspot`).
- The graph is the complete call graph of the default deployment (every `*_SERVICE_ADDR` in
  `kubernetes-manifests/` at v0.10.7). It leaves out `loadgenerator` (load tool) and the
  optional `shoppingassistantservice` (kustomize component).
- Rerun on 2026-10-19 after adding recommendationservice → productcatalogservice and
  C4-ADR-015 (zero-range features left out); the first T21 run had E04 first and E05 moving
  4th → 2nd.

## Reproduce (from `backend/`)

```powershell
$F = "tests/fixtures/degradation_scoring"
$common = @("--events", "$F/events/online_boutique_events.v1.json",
  "--graph", "$F/graphs/online_boutique_graph.v0.10.7.json",
  "--repo", "C:\repos\add-repositories\c4-history\microservices-demo",
  "--source-paths", "$F/mappings/online_boutique.source_paths.v1.json",
  "--data-provenance", "fixture-events+live-history")
uv run python -m scripts.c4_rank @common --adr-index "$F/adr/online_boutique" --run-id t21-ob-av-on
uv run python -m scripts.c4_rank @common --no-adr --run-id t21-ob-av-off
```
