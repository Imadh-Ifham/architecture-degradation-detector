# C4-ADR-010 — Persistence growth slope: relative, fastest-worsening metric

- **Status:** Accepted
- **Date:** 2026-10-18
- **Task:** C4-T15 Persistence
- **Decided by:** owner (Dahami)

## Context

§5.4 defines `growth_slope` as the OLS slope of an affected metric's `series` over release
index and leaves to T15 which metric is used. C3's metrics have very different units: on the
fixtures, `size` grows by about 700 lines per release and `instability` by about 0.05. Raw
slopes would therefore rank events by the unit of their metric: after min-max normalisation
(§5.5) every size event would look fast-growing and every instability event flat.

## Decision

1. `growth_slope` is the **relative** slope: OLS slope of the non-null values over release
   index, divided by the absolute mean of those values. It reads as "growth per release as a
   share of the metric's level" (0.10 = +10 % per release) and is comparable across metrics.
2. It is signed so that **positive = worsening**: for a metric with `worsening = DECREASE` the
   sign is flipped. An improving metric gives a negative value.
3. When an event has several affected metrics, the **fastest-worsening** one (largest signed
   relative slope) is used; its name is reported as `growth_metric`.
4. Fewer than two non-null values, or a mean of 0, gives `growth_slope = 0.0` with
   `growth_slope_available = false`. Release index keeps gaps (a null release still occupies
   its position), so a missing release does not compress time.
5. Only the series values are used, never C3's `tau`, `q_value` or `sen_slope` (§4.1: C3's
   evidence strength is not severity).

## Alternatives considered

- **Raw slope in metric units** (§5.4 as written). Rejected for the unit problem above.
- **First listed metric.** Rejected: C3's ordering of `affected_metrics` carries no stated
  meaning, so the result would depend on an accident.
- **Choose the metric by C3's `tau`.** Rejected: would make C3's trend strength a severity
  input through the back door.

## Consequences

- Tested in `features/test_persistence.py`: equal relative growth for a size and an
  instability series, DECREASE flipped, fastest metric chosen, unavailable cases.
- A metric whose level is near 0 gives a large relative slope; this is reported, and the
  winsorised normaliser (§5.5) limits its effect on the ranking.
