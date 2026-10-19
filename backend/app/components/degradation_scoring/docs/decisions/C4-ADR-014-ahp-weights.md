# C4-ADR-014 — AHP weights: one 4×4 judgement set, proportional renormalisation, RI table

- **Status:** Accepted
- **Date:** 2026-10-18
- **Task:** C4-T18 AHP
- **Decided by:** owner (Dahami)

## Context

§5.6 says the pairwise matrix is "over active criteria", while §5.3 says the weights
"renormalise proportionally over active criteria" when AV is off. These give different weights
unless the matrix is perfectly consistent. On the provisional `ahp_v1` matrix with AV off:

| Approach | BR | EH | PS | CR shown |
|---|---|---|---|---|
| Rescale the 4×4 weights (§5.3) | 0.556 | 0.330 | 0.114 | 0.01 (4×4, RI 0.90) |
| AHP on the 3×3 sub-matrix (§5.6) | 0.558 | 0.320 | 0.122 | 0.02 (3×3, RI 0.58) |

§5.6 also lists RI only for n = 3 and 4, does not say what CR is when n ≤ 2 (RI = 0), does not
name the textbook example, and the report contract had no field for the weights' provenance.

## Decision

1. **AHP always runs on the full 4×4 matrix**; inactive criteria get weight 0 and the active
   weights are divided by their sum (`renormalise` in `scoring_engine/ahp.py`). One elicitation
   session gives one set of judgements and one CR, and switching AV off removes only AV: the
   other criteria keep their relative sizes, as the ablation (§5.10) assumes. The CR gate is
   always applied to the 4×4 matrix, and the report's `ahp_cr` is its CR.
2. **RI = Saaty (1980) for n = 1..10** (0, 0, 0.58, 0.90, 1.12, 1.24, 1.32, 1.41, 1.45, 1.49);
   larger matrices are rejected. For n ≤ 2 a reciprocal matrix is always consistent, so CR is
   defined as 0. CI is clamped at 0 (rounding can put λmax a hair below n).
3. **Textbook check: Saaty (1990)**, "How to make a decision: The analytic hierarchy
   process", *EJOR* 48(1), 9–26, house example (8 criteria): weights .173 .054 .188 .018
   .031 .036 .167 .333, λmax 9.669, CR 0.169. Reproduced to 2 d.p.; being above 0.10 it also
   shows the gate refusing a published inconsistent matrix. The matrix in the test must be
   checked against the paper's table before the viva.
4. **Provenance in the report**: `SeverityReportV1.weights_provenance` (enum
   `provisional-author-elicited` | `supervisor-elicited`), schema version 1.0.0 → 1.1.0
   (additive). T20 copies `CriterionWeights.provenance` into it.
5. **The weights file is read inside `scoring_engine`** (`load_judgements`, from
   `scoring_engine/weights/<scoring_weights_version>.json`): it is versioned data shipped with
   the code, not an external system, so no port (same as the calibration files, T17).
6. **The file is validated strictly**: exact fractions, diagonal 1, Saaty 1–9 values or their
   reciprocals only, exact reciprocity, each of the four criteria once (matched by name, not
   position), one matrix row per criterion, no extra fields, no surrounding spaces in
   `elicited_by` (the T07 draft had a trailing space; fixed).

## Alternatives considered

- **AHP on the active sub-matrix (§5.6 as written).** Rejected (decision 1): with AV off it
  would report a CR for judgements nobody made as a set, and BR/EH/PS would shift relative to
  each other just because AV was switched off.
- **RI only for n = 3, 4.** Rejected: the published example needs n = 8, and the full table
  costs nothing.
- **Provenance only on `CriterionWeights` until T20.** Rejected: T18's acceptance criterion
  asks for it in the report contract.
- **Orchestrator reads the file and passes the matrix in.** Rejected (decision 5): more
  plumbing, no gain.

## Consequences

- CLAUDE.md §5.6 now says "over all four criteria; inactive criteria removed by proportional
  renormalisation (§5.3)".
- With the provisional matrix (CR 0.01): all four on → BR 0.47, EH 0.28, AV 0.16, PS 0.10;
  real PP1 runs (AV off) → 0.556 / 0.330 / 0 / 0.114; fixtures (EH off, AV off) → 0.830 / 0 /
  0 / 0.170. These are provisional numbers until the supervisor session (Y05).
- Tested in `scoring_engine/test_ahp.py` and `scoring_engine/test_service.py`.
