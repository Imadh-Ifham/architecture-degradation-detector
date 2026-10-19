# Graph construction: release-aware validation

Validated against the Google Online Boutique repository at two real releases,
through the real pipeline: revision-aware ingestion -> repository inventory ->
manifest analysis -> component discovery -> dependency resolution -> source code
analysis -> graph construction -> Neo4j.

No expected element or relationship was hardcoded in the builder.

## Analyzed releases

| Release | Commit | Elements | Relationships | Order source | Snapshot |
| --- | --- | --- | --- | --- | --- |
| `v0.9.0` | `d138db567079` | 12 | 16 | `release_date` (2023-12-18) | `snapshot:d85955914869fac5` |
| `v0.10.0` | `98e60f5ee0b6` | 13 | 17 | `release_date` (2024-04-23) | `snapshot:68775e608cf1b888` |

Both snapshots were stored in Neo4j under one repository id
(`microservices-demo-ffb04a16f525`), and both remained readable after the second
release was analyzed.

## What the comparison shows

- **Elements added.** `shoppingassistantservice` appears in `v0.10.0` and not in
  `v0.9.0`.
- **Elements unchanged in identity.** `frontend`, `checkoutservice`,
  `productcatalogservice` and the rest keep the same `logical_id` in both
  snapshots, while their snapshot-scoped node ids stay separate.
- **Sizes changed.** `frontend` 66 -> 71 files, `cartservice` 19 -> 17,
  `adservice` 13 -> 12, `productcatalogservice` 10 -> 11,
  `recommendationservice` 10 -> 9, `paymentservice` 11 -> 10.
- **Relationships added.** `frontend -> shoppingassistantservice` exists only in
  `v0.10.0`; the other 16 relationships are common to both releases.
- **Relationships removed.** None between these two releases.
- **Evidence.** Every relationship in both snapshots is confirmed by source
  code (`confirmed_by_source`), not only by configuration.
- **Provenance.** Each snapshot records the repository id, repository url,
  release tag, resolved commit SHA, release date and its source, branch, analysis
  id and analysis timestamp.

## Identity observation

At `v0.9.0` and `v0.10.0`, component discovery reports most components as
`heuristic` associations, so their `logical_id` carries
`identity_basis: heuristic`. `redis-cart` and `shoppingassistantservice` are
`direct`. The snapshot preserves that distinction rather than presenting every
name match as a certain identity.

## Query shape the store supports

```cypher
// history, oldest first
MATCH (s:ArchitectureSnapshot {repository_id: $repository_id})
RETURN s ORDER BY s.order_timestamp ASC, s.snapshot_id ASC;

// one element across releases
MATCH (e:ArchitectureElement {repository_id: $repository_id})
WHERE e.logical_id = 'frontend'
RETURN e.snapshot_id, e.size, e.size_unit ORDER BY e.snapshot_id;

// one release's architecture
MATCH (:ArchitectureSnapshot {repository_id: $repository_id,
                              snapshot_id: $snapshot_id})
      -[:CONTAINS]->(e:ArchitectureElement)
RETURN e;

// relationships of one release
MATCH (a:ArchitectureElement {repository_id: $repository_id,
                              snapshot_id: $snapshot_id})
      -[d:ARCHITECTURE_DEPENDENCY]->
      (b:ArchitectureElement {repository_id: $repository_id,
                              snapshot_id: $snapshot_id})
RETURN a.element_id, d.kind, b.element_id;
```

## Test results

| Suite | Result |
| --- | --- |
| `tests/components/architecture_recovery/test_graph_construction.py` | 22 passed |
| `tests/infrastructure/neo4j/test_architecture_snapshot_store.py` | 8 passed (real Neo4j) |
| `tests/infrastructure/git/test_git_revision.py` | 6 passed |
| `tests/api/test_repositories.py` | 24 passed |

## Limitations

- The graph contains one node per component per snapshot. A component that moves
  directory between releases is a new snapshot element with the same logical id;
  nothing is merged across snapshots.
- Sizes are source-file counts (`size_unit: files`) supplied by component
  discovery. A component deployed from an image with no source project has no
  size.
- A logical id is the normalised component name and only when that name is
  unique in the release. Two components sharing a name get no logical id, so
  their history cannot be silently joined.
- Each snapshot preserves one unresolved reference: `frontend` reads
  `PACKAGING_SERVICE_URL` but no component matches that target. It is recorded
  as unresolved rather than dropped or guessed. At `v0.10.0` the frontend HTTP
  call to the shopping assistant is configured and confirmed, which is why that
  release adds exactly one relationship.
- This stage stores and reports; it does not compute degradation scores, and it
  does not write to the validated graph's `(:Release)`/`(:Element)` labels.
