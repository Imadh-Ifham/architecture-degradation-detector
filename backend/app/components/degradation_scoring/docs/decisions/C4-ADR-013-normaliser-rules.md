# C4-ADR-013 — Normaliser rules: hotspot weights, AV unscaled, sparse fallback, percentiles

- **Status:** Accepted
- **Date:** 2026-10-18
- **Task:** C4-T17 Normaliser
- **Decided by:** owner (Dahami)

## Context

§5.5 normalises "each feature" with a winsorised P5–P95 min-max and gives 0.5 to every
event when the range is zero. Implementing it raised four questions §5 does not answer:
the hotspot criterion has no feature weights (BR and PS have them), AV is already on a fixed
0–1 scale, sparse features (one non-zero value among many zeros) have P5 = P95 = 0, and the
percentile method is not named.

## Decision

1. **Hotspot feature weights: 0.25 each**, as settings `scoring_eh_weight_churn_decayed`,
   `_authors`, `_coupling`, `_bugfix_ratio` (same pattern as `scoring_br_weight_*`). Equal
   weights are the honest default without evidence for another split.
2. **AV is not normalised.** `status × scope × explicitness` already means the same thing in
   every run (1.0 = accepted system-wide ADR). Min-max would turn a weak superseded ADR (0.2)
   into 1.0 whenever it is the strongest in the run. AV passes through as its criterion value
   and gets no bounds in the calibration.
3. **Sparse fallback.** If P5 = P95 but the values differ, that feature uses plain min-max
   (its bounds carry `fallback = "sparse_minmax"`, logged `reason=sparse_minmax`). Otherwise
   the one event with coupling > 0 would get 0.5 like everyone else and lose exactly the
   signal the feature exists for. 0.5 for all (with a `zero_range` warning) remains for a
   feature whose values are truly all equal.
4. **Percentiles = numpy's default linear interpolation** (same as Excel `PERCENTILE.INC`),
   standard and checkable by hand.

## Alternatives considered

- **No hotspot weights / one fixed hotspot feature.** Rejected: §5.1 and §5.4 combine all
  features of a criterion; hotspot should not differ.
- **Normalise AV like the rest (§5.5 as written).** Rejected (decision 2).
- **Keep 0.5 for every zero P5–P95 range.** Rejected (decision 3).
- **`lower`/`higher` percentile methods** (more resistant to one outlier at small n).
  Rejected: non-standard and harder to explain; the limitation below is stated instead.

## Consequences

- Limitation (declared): with 10–20 events one outlier is 5–10 % of the data, which is not
  beyond the 5 % tail, so winsorising cannot fully remove its pull. The outlier test uses
  n = 40. Below 10 events plain min-max is used anyway (`minmax_small_n`; the fixture run).
- Tested in `scoring_engine/test_normalizer.py` (hand-computed P5/P95, sparse fallback, AV
  pass-through, zero range, frozen bounds, save/load).
- Rows `c4_event_scores` (normalised values, criteria, severity, rank) are added once, in T19
  (migration `0004`), not in T17.
