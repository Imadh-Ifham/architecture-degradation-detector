# C4-ADR-015 — A zero-range feature is left out of its criterion's mean

- **Status:** Accepted (deviation from CLAUDE.md §5.5; replaces the "0.5 kept when all values
  are equal" part of C4-ADR-013)
- **Date:** 2026-10-19
- **Task:** follow-up to C4-T21 (real-repo run on Online Boutique)
- **Decided by:** owner (Dahami)

## Context

§5.5 says a feature whose values are all equal in a run (zero range, `P95 = P5` or
`max = min`) gets 0.5 for every event, with a warning. A criterion score is the weighted mean
of its normalised features (§5.1, §5.2, §5.4), so that 0.5 still goes into the mean. It
carries no information (every event gets it), but it pulls every event's criterion score
towards the middle and shrinks the spread the real features create. Example: with four
blast-radius features of which three are constant, an event with the largest fan-in got
BR 0.625 instead of 1.0, and the one with the smallest got 0.375 instead of 0.

The T21 run on Online Boutique has several constant hotspot features (e.g. `eh_coupling` is 0
for all six events), so this happens on real data, not only in edge-case tests.

## Decision

1. **Left out.** A feature with zero range in the bounds used for the run (fitted or frozen)
   is left out of its criterion's weighted mean. The mean is taken over the remaining
   features, with their weights renormalised.
2. **All constant gives 0.** If every feature of a criterion has zero range, the criterion
   value is 0 for every event (the criterion separates nothing in this run). AV is not
   affected: it is not normalised (C4-ADR-013).
3. **Recorded.** The feature's bounds carry `fallback: "zero_range"` (calibration file,
   manifest `normalization.bounds`, `c4_scoring_run.details.scoring`). The log has a
   `normalisation_zero_range` warning per feature (`action: left_out`) and a
   `normalisation_constant_criterion` warning per criterion that drops to 0. The report
   contract is unchanged (schema 1.1.0): such a feature shows `lower = upper` in
   `normalization_bounds`.
4. A frozen calibration saved before this decision (no mark) is treated the same way, because
   the check is `lower == upper`.

## Alternatives considered

- **Keep 0.5 (§5.5).** Rejected: it adds the same number to every event and flattens the
  differences the informative features produce.
- **Give 0 to the feature but keep it in the mean.** Rejected: it still dilutes the mean, just
  towards 0 instead of 0.5.
- **Drop the whole criterion from TOPSIS when it is constant.** Rejected: it would change the
  AHP weights per run and break comparability between runs; a constant 0 column adds the same
  distance to every event under fixed-reference TOPSIS (C4-ADR-002).

## Consequences

- Criterion scores spread over the full [0, 1] range of the features that vary.
- The fixture run is unchanged (it has no zero-range feature): the golden report did not
  change. The T21 Online Boutique reports were regenerated.
- Tests: `scoring_engine/test_normalizer.py` (left out + hand-computed criteria, all-constant
  criterion = 0, frozen bounds without the mark, `criterion_value` over present features,
  `scale` refuses a zero range).
