# C4-ADR-003 — Edge direction: "A → B" means A depends on B

- **Status:** Accepted
- **Date:** 2026-10-18
- **Task:** C4-T09 Graph loader

## Context

Blast radius (§5.1) asks "how much of the system depends on this element?". The answer is
only right if C4 knows which way the graph's edges point. A reversed graph would not raise
an error: it would silently rank the most *dependent* elements as the most *depended on*.

C3's release package (`ReleasePackageV1.1`, the graph C4 loads, C4-ADR-007) stores
`dependencies[]` as `{from, to}`, where `from` calls / depends on `to`. C2's validated graph
uses `source → target` in the same sense.

## Decision

1. Inside C4, an edge `A → B` always means **A depends on B**. The dependents of X are
   therefore `nx.ancestors(G, X)`, and its dependencies are `nx.descendants(G, X)`.
2. `ingestion/graph.py` builds edges as `from → to`, with `weight` = dependency `count`.
   Like C3's normaliser, duplicate edges collapse (counts summed) and self-loops are dropped,
   so C4's graph is the one C3 analysed.
3. If an upstream graph ever uses the opposite convention, `scoring_graph_reverse_edges =
   true` flips every edge at load time. The default is `false`. Changing it needs a new note
   here, because it changes every blast-radius value.
4. Node-link documents must keep edges under `links`; a document with only `edges` is
   refused, because networkx would otherwise load it with no edges and no error.

## Alternatives considered

- **"A → B" means B depends on A** (dependency arrows pointing at the dependent). Rejected:
  it is the opposite of both upstream formats, so every load would need a reversal.
- **Detect direction automatically** (e.g. from which nodes are roots). Rejected: no rule
  is reliable on a cyclic graph, and a wrong guess fails silently.

## Consequences

- Tested in `tests/components/degradation_scoring/ingestion/test_graph.py`: dependents =
  ancestors on the fixture graph, the reverse flag flips a chain, and a node-link document
  without `links` is refused.
- Every manifest records the flag (T20), so a reversed run is visible.
