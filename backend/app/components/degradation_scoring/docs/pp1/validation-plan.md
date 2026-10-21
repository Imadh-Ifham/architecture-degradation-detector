# C4 validation plan — does severity reflect real maintenance impact?

Answer to the proposal-defence comment: *how will C4 show that a high severity means a
degradation that really costs maintenance effort, rather than one that only looks bad?*

**Short answer.** C4's severity is a *prediction made at detection time*. We validate it
against what developers and the code base *did afterwards*, using signals C4 never sees when it
ranks: later change- and fault-proneness, later refactorings, and developers' own judgement.
A ranking is useful only if it beats simple baselines on these signals, and every criterion
must earn its place in an ablation. The decision point is Gate 3.

## 1. What "real maintenance impact" means (three signals, triangulated)

| Signal | What it measures | Source | Why it is independent of the ranking |
|---|---|---|---|
| **S1 Post-detection change- and fault-proneness** | For each event, the churn, number of commits and bug-fix commits touching its elements in the *N releases after* detection (default N = 2), normalised by element size | Git history via the existing `CommitHistorySource` + mining cache; same path mapping as hotspot | Only history **after** the detected release is used; the hotspot criterion uses history **before** it (no overlap of commit ranges) |
| **S2 Refactoring attention** | Whether developers later refactored the flagged elements (move/extract class, extract interface, move method across the flagged dependency, etc.) within N releases | RefactoringMiner on a Java evaluation repository (Y04b; Online Boutique is polyglot, so it cannot be labelled this way) | Labels come from code changes developers chose to make, detected by an external tool |
| **S3 Developer judgement** | Practitioners rank or rate a sample of events ("fix first … ignore") | Small survey (10–20 practitioners, 10–15 events each, randomised order, blind to C4's score); agreement with Krippendorff α | Human judgement, collected without showing the model's ranking |

Each signal is imperfect on its own: S1 can be inflated by routine maintenance (e.g.
dependency bumps — already filtered by the source-file globs), S2 is a proxy for attention, not
harm, and S3 is small. A claim is made only where they agree.

## 2. Metrics

- **Ranking quality against S1/S2 labels:** nDCG@k (k = 5, 10), precision@k, MAP.
- **Rank agreement with continuous S1 and with S3:** Kendall's τ and Spearman's ρ.
- **Uncertainty:** 1,000-resample bootstrap 95 % CIs (seed 42), reported for every metric.
- All runs are manifest-tracked; every number on a slide is regenerable (NFR-01).

## 3. Baselines (C4 must beat them, not just score well)

| Baseline | Why it matters |
|---|---|
| **Random** ordering (1,000 shuffles, mean and CI) | The floor; shows the signal is not noise |
| **Structural-only** (blast radius alone) | What a dependency-graph tool would give; tests whether history, decisions and persistence add value |
| **Single-signal** baselines: C3's `trend_strength`; hotspot alone | Shows the fusion beats its strongest single input (and that C3's evidence strength is not severity) |
| **Classic TOPSIS** and **weighted sum** with the same weights | Separates the effect of the method from the effect of the criteria |
| **LambdaMART** (stretch, M5) | A learned ranker trained on S2 labels with grouped cross-validation, as an upper reference, not the contribution |

## 4. Ablation

Remove one criterion at a time (BR, EH, AV, PS), renormalise the remaining weights (the
mechanism already used for AV off, C4-ADR-014) and report **Δ-nDCG@10 with bootstrap CIs**,
plus the criteria correlation matrix. A criterion whose removal does not lower nDCG (CI includes
0) is reported as not contributing. AV is ablated on every system, since it is optional by design.

## 5. Threats to validity (and what we do)

| Threat | Mitigation |
|---|---|
| **Leakage**: hotspot uses history, S1 is history | Strictly disjoint commit ranges (before vs after detection); report results with and without the hotspot criterion |
| **Autocorrelation**: busy code stays busy | Compare against the hotspot-only baseline; C4 must add value beyond "recently changed" |
| Refactoring ≠ harm | Treated as attention, triangulated with S1 and S3 |
| Few events per system | Pool across systems/releases; always show CIs; no claim from a single system |
| Fixture inputs today | PP1 numbers are labelled fixture or pilot; real evaluation needs C3's events on real releases |
| Provisional AHP weights | Supervisor elicitation (Y05); sensitivity analysis of the weights |

## 6. Gate 3 (decision point)

At Gate 3 the evaluation runs on the real C3 events of the evaluation systems:

- **Pass:** C4's nDCG@10 beats random **and** structural-only, with non-overlapping 95 % CIs,
  on S1 or S2, and agrees with S3 (τ > 0, CI excluding 0).
- **Partial:** beats random but not structural-only → report that history/decision criteria add
  no measurable value on these systems; keep the explanation contribution; adjust the claim.
- **Fail:** no better than random → the severity model is reported as not validated; the
  framework (contracts, audit, ablation harness) and negative result are the contribution.

## 7. Timeline

| When | Step |
|---|---|
| PP1 (22 Oct) | Mechanism only: ranking, manifests, AV ablation, optional S1 pilot (below) |
| M5 | S2 labels on the Java evaluation repo (RefactoringMiner), metrics + bootstrap + baselines + ablation code |
| M6 | S1 on all evaluation systems; full ablation |
| M7 | Survey (S3); Gate 3 decision |

## 8. Optional PP1 pilot: post-detection change-proneness (not built)

*Rank the Online Boutique events as if detected at an earlier release (e.g. v0.10.4), mine
v0.10.4 → v0.10.7 per event with the existing history code, compute future churn and bug-fix
commits, report Spearman ρ between severity and each — labelled "pilot / mechanism only".*
Feasibility assessment: see the hand-over message; it is built only after the owner approves.
