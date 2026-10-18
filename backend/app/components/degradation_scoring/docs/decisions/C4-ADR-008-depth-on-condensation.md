# C4-ADR-008 — Blast-radius depth is always measured on the condensation

- **Status:** Accepted
- **Date:** 2026-10-18
- **Task:** C4-T11 Blast-radius engine
- **Decided by:** owner (Dahami)

## Context

Depth (§5.1) says how far an element sits below the system's entry points: the longest of
the shortest paths from any root (a node nothing depends on) to the element. The plan
computed it on the graph itself and switched to `nx.condensation(G)` (every cycle collapsed
into one node) only when `G` has no roots at all.

That rule gives odd answers on the common case of a graph that has roots *and* a cycle.
With `r → a → b → c → a`, the raw graph puts `a`, `b`, `c` at depths 1, 2 and 3, although
they are one tangled unit that `r` reaches in one step. The depth of a cycle member then
depends on where the cycle is "entered", which is an accident of the graph, and a cyclic
dependency event (C3's `CyclicDependency`, fixture E01) gets a larger depth than its
structure justifies.

## Decision

Depth is **always** computed on the condensation: roots are the in-degree-0 nodes of
`nx.condensation(G)`, and every node gets the depth of its strongly connected component.
For an event with element set `S`, `depth = max` over `v ∈ S` of that node depth.
Implemented in `features/blast_radius.py` (`node_depths`), computed once per
`(system, release)` together with PageRank and betweenness.

## Alternatives considered

- **Condensation only when there are no roots** (the plan). Rejected for the reason above:
  cycle members get different depths, and a graph with one root and one cycle behaves
  differently from a graph with only the cycle.
- **Longest path instead of shortest.** Undefined on a cyclic graph without condensing, and
  it would change the plan's definition, not only its cycle handling.

## Consequences

- On an acyclic graph the condensation is the graph itself, so the value is unchanged. The
  old prototype's 13-module graph is acyclic and its depths are reproduced exactly
  (`features/test_blast_radius_prototype.py`).
- All members of a cycle share one depth (`test_cycle_members_share_the_depth_of_their_cycle`;
  on the fixture, the four cycle services all have depth 3).
- A fully cyclic graph gives depth 0 for every node, as the plan intended.
