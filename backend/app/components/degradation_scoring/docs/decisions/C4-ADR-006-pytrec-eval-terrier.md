# C4-ADR-006 — `pytrec-eval-terrier` replaces `pytrec_eval`

- **Status:** Accepted
- **Date:** 2026-10-18
- **Task:** C4-T03 Tooling & quality gates

## Context

CLAUDE.md §5.10 computes nDCG@k, P@k and MAP with `pytrec_eval`, the Python
binding of TREC's standard `trec_eval` tool, so ranking metrics match how the
information-retrieval literature computes them.

The dependency check in C4-ADR-000 §3 found that `pytrec_eval` (latest 0.5) ships
**no prebuilt wheels**: installing it on Python 3.13 needs a C++ compiler, and fails
without one on both Windows and Linux.

## Decision

Use **`pytrec-eval-terrier`** (locked at 0.5.11), a maintained fork published by
the Terrier IR group. It installs from prebuilt wheels for CPython 3.13 on Windows
and Linux and keeps the same import name (`import pytrec_eval`) and API, so no C4
code changes. It is in the `scoring-ml` dependency group.

CLAUDE.md §5.10's safeguard stays: `evaluation/metrics.py` cross-checks nDCG
against `sklearn.metrics.ndcg_score` in its unit tests, so a defect in either
library would show up as a failing test.

## Alternatives considered

- **Build `pytrec_eval` from source.** Rejected: every developer and CI runner would
  need a C++ toolchain.
- **Implement the metrics ourselves only.** Kept as the cross-check, not the primary:
  a reference implementation is easier to defend to a panel than hand-written code.
- **`ir-measures` / `ranx`.** Viable, but they would also replace the `trec_eval`
  semantics the plan cites; not needed when a drop-in fork exists.

## Consequences

- Metrics remain `trec_eval`-compatible, and the import line in the plan is unchanged.
- Version pinned through `backend/uv.lock`; the fork's release cadence is a minor
  maintenance risk, mitigated by the scikit-learn cross-check.
