# ADR 0002 — Detect architectural anti-patterns, not code smells

- **Status:** Accepted (supervisor direction, plan v3)
- **Date:** 2026-10-13
- **Component:** C3 Degradation Detection
- **Source:** [implementation plan](../implementation-plan.md) Sections 1.1, 1.2 and 4 (M2–M4)

## Context

Version 2 of the C3 design tracked per-element metric "smells" across releases. The supervisor
asked for the unit of detection to be the **architectural anti-pattern**: a named, usually
multi-element bad structure such as a dependency cycle or a hub. A smell on one element does not
say which structure is degrading, and it cannot follow a structure whose membership changes from
release to release.

## Decision

1. C3 detects architectural anti-patterns in every release. Each detector is an automated
   **fitness function** over the validated architecture graph.
2. Each detected **instance** is tracked across releases (members mapped to element lineages,
   matched by Jaccard overlap), so a cycle that gains a member stays the same instance.
3. Presence is not degradation. An instance, element or system is reported only when a tracked
   measure shows a statistically significant **worsening trend** (Mann-Kendall, Sen's slope,
   Benjamini-Hochberg). Detector thresholds decide presence only, are relative to each release's
   own distribution, and come from configuration.
4. Detectors live in a catalog with tiers: a **universal** tier that runs for every architecture
   style, and style tiers (microservices, layered) selected by `architecture_style`. The
   detector registry is the only place that branches on style.
5. Detector ids are style-neutral: `OversizedElement` (not "God Component") and `HubLikeElement`.

## Out of scope

Decision anti-patterns from *Fundamentals of Software Architecture* ch. 19 (Covering Your Assets,
Groundhog Day, Email-Driven Architecture). They are not detectable from code structure, and ADR
analysis belongs to C2.

## Consequences

- The output event changes shape (`anti_pattern_type`, `scope`, `instance_id`, `members`,
  `lifecycle`), which is a major contract bump. See [ADR 0003](0003-v2-v3-contract-reconciliation.md).
- M3 gains instance tracking on top of element alignment, and series exist at three scopes
  (element, instance, system).
- Cycle measures are SCC-based. Simple cycles are never enumerated without a bound.
- A structure that is bad but stable produces no event. That is intended: it is the contrast
  with a static-threshold baseline that the evaluation measures.
- C3 still assigns no severity. Ranking stays with C4.
