# Hotspot profile — Online Boutique (C4-T14, 2026-10-18)

Live git history of GoogleCloudPlatform/microservices-demo + **manual source-path mapping**
(`src/<service>/**`, C4-ADR-011). Pilot evidence of the mining mechanism, not a finding.
Regenerate: `uv run python -m scripts.c4_hotspot_profile --from-tag v0.10.4 --to-tag v0.10.7`
(and `--from-tag v0.10.0 --name online_boutique_wide`). Manifests: `hotspot_*.manifest.json`.

**Clone location:** `C:\repos\add-repositories\c4-history\microservices-demo` (full history and
tags; `REPOSITORIES_ROOT=C:\repos\add-repositories` in `backend/.env`). Runs 1–2 below used the
earlier temp-folder copy; run 3 is the same window on the new clone (same HEAD `38e7348e`).

## Runs

| Window | Releases | Run | Cache | History load (s) | Whole run (s) | Commits kept | Lines | Unmapped line share |
|---|---|---|---|---|---|---|---|---|
| (v0.10.4, v0.10.7] | 3 (Nov 2025 → Sep 2026) | 1 | miss | 15.389 | 15.625 | 4 | 301 | 0.0 |
| (v0.10.4, v0.10.7] | | 2 | **hit** | 0.005 | 0.215 | 4 | 301 | 0.0 |
| (v0.10.4, v0.10.7] | new clone path | 3 | miss (new path) | 14.377 | 14.674 | 4 | 301 | 0.0 |
| (v0.10.4, v0.10.7] | new fix rule | 4 | **hit** | 0.003 | 0.235 | 4 | 301 | 0.0 |
| (v0.10.0, v0.10.7] | 7 (Apr 2024 → Sep 2026) | 1 | miss | 48.371 | 48.567 | 9 | 506 | 0.0 |
| (v0.10.0, v0.10.7] | | 2 | **hit** | 0.004 | 0.243 | 9 | 506 | 0.0 |
| (v0.10.0, v0.10.7] | new clone path, new fix rule | 3 | miss (new path) | 38.965 | 39.199 | 9 | 506 | 0.0 |

Second run = 1.4 % (recent) and 0.5 % (wide) of the first run's time (target ≤ 10 %, NFR-03),
with byte-identical feature tables; run 3 on the new clone gave identical features too.
Runs 1–3 used the first bug-fix rule (fix words or issue keys); run 4 (recent) and run 3
(wide) use the current rule, fix words only (C4-ADR-009). The rule is applied after the
cache, so run 4 still reads the cached commits; only `bugfix_ratio` changed.
Half-life = 2 × median gap of the v0.10.x releases = 214.1 days (λ = 0.00324 / day).

## Per-service features, recent window

See `hotspot_online_boutique.csv` (and `_wide.csv`), current rule. Shipping service is the
hottest (churn 78.7 from 2 commits by 2 authors); 6 of 12 services had no source change.

| Service | churn_decayed | authors | coupling | bugfix_ratio | commits |
|---|---|---|---|---|---|
| shippingservice | 78.696 | 2 | 0 | 1.0 | 2 |
| frontend | 17.161 | 1 | 0 | 1.0 | 1 |
| recommendationservice | 15.079 | 1 | 0 | 0.0 | 1 |
| emailservice | 14.648 | 1 | 0 | 0.0 | 1 |
| productcatalogservice | 12.778 | 2 | 0 | 1.0 | 2 |
| checkoutservice | 6.630 | 1 | 0 | 1.0 | 1 |
| 6 others | 0 | 0 | 0 | 0.0 | 0 |

## What the profile shows

1. **Sparse source history.** The recent window has 195 non-merge commits, but only 4 touch
   source files kept by the filter; the rest are dependency and config bumps (YAML,
   Dockerfile, go.mod/go.sum, package.json). Online Boutique is in maintenance mode.
2. **Coupling is 0 everywhere**: no service pair shares the θ = 5 commits needed.
3. **First rule: `bugfix_ratio` was 1.0 for every changed service**, because a bare `#123`
   counted as an issue key and GitHub squash merges end every message with `(#PR)`. Fixed by
   counting fix words only (owner, C4-ADR-009): the recent window now has 0.0 for email and
   recommendation (their only change is "Bundle of dependency updates … (#3196)"), and the
   wide window ranges
   0.0–1.0.
4. Online Boutique gives weak hotspot variation; the Java evaluation repository (Y04b) should
   be checked for denser history.
