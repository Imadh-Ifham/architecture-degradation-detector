# C4-ADR-002 — Fixed-reference TOPSIS as the default, classic TOPSIS kept as a comparator

- **Status:** Accepted
- **Date:** 2026-10-18
- **Task:** C4-T19 TOPSIS
- **Decided by:** owner (Dahami); the locked learning in CLAUDE.md §5.7

## Context

TOPSIS scores each event by how close it is to an *ideal* event and how far from an
*anti-ideal* one. Classic TOPSIS builds both from the events in the run (best and worst value
per criterion) and divides each column by its vector norm. So an event's score depends on
which other events are in the run. Adding an event can swap two existing events even when the
new event says nothing about them. This is called *rank reversal*. C4 ranks a changing set of
events release after release, so this would make rankings unstable for reasons that have
nothing to do with the events themselves.

## Decision

1. **`fixed_reference` is the default** (`scoring_topsis_mode`). It uses the normalised [0, 1]
   values from §5.5 directly: `v = w · x`, ideal `A⁺ = w` (every criterion at 1), anti-ideal
   `A⁻ = 0`. An event's score then depends only on its own values and the weights.
2. **`classic` is also implemented** (vector normalisation, ideal and anti-ideal = best and
   worst event of the run). It shows rank reversal in the demo and is cross-checked against
   `pymcdm` 1.4.0 (`TOPSIS(normalization_function=vector_normalization)`; pymcdm's default is
   min-max, which is not classic TOPSIS).
3. **Common rules (both modes)**, per §5.7: `S = d⁻ / (d⁺ + d⁻)` (0 when both distances are 0);
   rank by `S` descending with ties broken by `event_id`; contribution
   `c_j = (v_j − A⁻_j)² / Σ_j (v_j − A⁻_j)²`, all 0 for an event on the anti-ideal point.
   Inactive criteria are left out of the calculation (the same as weight 0) and contribute 0.
   In classic mode an all-zero column stays 0 instead of dividing by 0.
4. **`ScoringService.rank()` is the one entry method** (CLAUDE.md §3: one public entry method
   per service): normalise → AHP weights → TOPSIS. The earlier `normalise()`/`weights()` steps
   are private.
5. **Run record:** `c4_event_scores` (migration `0006`, keyed by `(run_id, event_id)`, cascades
   from `c4_event_features`): rank, severity, both distances and, per criterion, the normalised
   value (NULL when off), weight and contribution (0 when off). Run-level scoring facts (mode,
   weights version and provenance, AHP CR and λmax, normalisation mode and bounds) go in
   `c4_scoring_run.details.scoring`, so that table's columns are unchanged.

## Alternatives considered

- **Classic TOPSIS as the default.** Rejected: rank reversal (see the test below).
- **Weighted sum `Σ w_j x_j`.** Also free of rank reversal on fixed bounds, but it treats the
  criteria as perfectly interchangeable. TOPSIS measures distance to both reference points, so
  an event that is extreme on one criterion and an event that is moderate on all of them score
  differently. It is also the method the plan names.
- **Rounding scores before tie-breaking.** Rejected: §5.7 says ties are broken by `event_id`.
  Identical inputs give identical floats, so the ranking is still deterministic.

## Consequences

- Rank-reversal test (`scoring_engine/test_topsis.py`): E1 = (0.2, 0.2), E2 = (0.1, 0.5),
  weights 0.5/0.5. Adding E3 = (0, 0.2), which is worse than both on every criterion, swaps
  them in classic mode (E2 0.555 > E1 0.445 becomes E1 0.631 > E2 0.606). In fixed mode E1 stays
  0.2 and E2 0.331. A property test checks that adding *any* event never changes the existing
  fixed-mode scores.
- Limitation (declared): fixed-reference TOPSIS removes the TOPSIS-level dependence on the event
  set. The normaliser's bounds still come from the run's events unless a frozen calibration
  (§5.5) is loaded, so full stability across releases needs the frozen bounds.
- Fixture runs (AV on): BR 0.647, AV 0.221, PS 0.132 → top event E01 (0.686). With AV off E02
  leads (0.754); only E01 and E02 swap places. Fixture numbers, not findings.
