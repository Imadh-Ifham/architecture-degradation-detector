# C4 commercialisation one-pager

**Product idea.** A severity-ranking step for architectural degradation: it takes the findings
of any degradation detector and returns a short, explained, reproducible "fix first" list.

## Users

| User | Situation |
|---|---|
| **Tech lead / architect** of a long-lived system (primary) | Owns the refactoring budget for the next release; must justify it to product owners |
| **Engineering manager** | Needs a defensible view of architectural risk across teams and releases |
| **Platform / DevEx team** | Runs code-quality tooling in CI for many repositories |
| **Consultancies doing architecture reviews** | Need evidence-backed priorities quickly on unfamiliar code |

## Pain

- Detectors produce **long, flat lists** of architectural problems (cycles, hubs, unstable
  dependencies); teams cannot tell which few matter, so lists get ignored.
- **Opaque scores**: when tools do rank, users cannot see why, so they cannot argue for the fix.
- Priority ignores **context**: how much depends on the element, how busy the code is, whether
  it breaks a recorded decision, and how long it has persisted.
- Results are **not reproducible** across runs, so trends and audits are unreliable.

## Benefits (achievable, measurable)

| Benefit | How C4 delivers it | Measure |
|---|---|---|
| A short shortlist instead of a flat list | Ranked top-N per release (e.g. 17 fixture events → 9 ranked, 4 skipped, 4 quarantined with reasons) | Events a lead must read per release |
| Decisions that can be defended | Every score splits into four criteria with weights and contributions | Share of fix decisions with a cited reason |
| Works on real codebases without ADRs | ADR criterion optional; weights renormalise | Runs on systems with 0 ADRs |
| Trustworthy over time | Fixed-reference TOPSIS, frozen bounds, manifests with hashes | Byte-identical reruns; stable ranks when events are added |
| Cheap to run in CI | Cached history mining (≈ 10 min first time → 4.5 s) | CI step duration |
| Evidence of effect (planned) | Validation against later change/fault-proneness, refactorings and developer survey | nDCG@10 vs baselines (Gate 3) |

## Positioning

| Tool | What it does well | Gap C4 fills |
|---|---|---|
| **CodeScene** | Behavioural code analysis: prioritises code hotspots from change activity and code health | Ranks *architectural* degradation events, combining structure, decisions and persistence with history |
| **Arcan** | Detects architectural smells (cycles, hubs, unstable dependencies) from dependency structure | Consumes such findings and adds an evidence-fused, reproducible severity with a per-criterion breakdown |
| **Sonargraph** | Checks code against a defined architecture model; dependency and cycle metrics | Does not need a full architecture model; ranks what a detector found, with ADR violation as an optional signal |

C4 is **complementary**: it sits after a detector (here C3), so it can work with existing tools
rather than replace them. (Check each competitor's current feature list before the viva.)

## Delivery model

1. **CI step** (primary): run after detection on each release tag; publishes the JSON report
   and fails or warns when a new event enters the top-N.
2. **Report**: static HTML + JSON + manifest per run, attachable to a release or review.
3. **UI page**: the group UI's Severity page over a read-only API (working at PP1).

Pricing hypothesis (to test): free for open source; per-repository subscription for teams;
consulting package for architecture reviews.

## Next validation step

- Three conversations with tech leads (Y07): "how do you decide which architecture problems to
  fix first?" — confirm the pain and which criteria they trust.
- Gate 3 evaluation: show the ranking beats structural-only and random baselines on real
  systems before claiming the benefit "fix the right things first".
