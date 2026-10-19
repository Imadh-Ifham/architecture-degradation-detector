# Test Guide — Graph Construction

A quick-reference guide to
[test_graph_construction.py](./test_graph_construction.py). Each entry describes
**what the test attempts to prove**, not just which function it calls.

- **Subject under test:** `app.components.architecture_recovery.graph_construction`
- **Scope:** 22 tests, plus Neo4j integration tests in
  [`tests/infrastructure/neo4j/test_architecture_snapshot_store.py`](../../infrastructure/neo4j/test_architecture_snapshot_store.py)
  and API tests in [`tests/api/test_repositories.py`](../../api/test_repositories.py).
- **Fixtures:** two releases under
  [`tests/fixtures/graph_construction/`](../../fixtures/graph_construction) —
  `release_v1` and `release_v2`.
- **Run it:** `cd backend && uv run pytest
  tests/components/architecture_recovery/test_graph_construction.py`

Each release fixture is run through the real inventory, manifest analysis,
component discovery, dependency resolution and source code analysis first. The
history store in these tests is an in-memory implementation of the same port the
Neo4j adapter satisfies; the Cypher that enforces the identity rules is covered
by the Neo4j suite.

## 1. Two releases, both preserved

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_two_releases_produce_separate_snapshots` | Two commits produce two snapshot ids, and both rows exist afterwards. |
| `test_both_snapshots_remain_queryable_after_the_second_release` | The first release still returns its elements and relationships after the second is published, and history lists both in order. |

## 2. Comparison across releases

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_unchanged_component_keeps_its_logical_identity` | `frontend` keeps `logical_id: frontend` in both releases while the snapshots stay separate. |
| `test_component_size_can_differ_between_releases` | `frontend` is 2 files in v1 and 3 in v2, with the same unit. |
| `test_relationships_are_added_without_changing_the_earlier_snapshot` | v2 adds `cart` and one relationship; the stored v1 snapshot is unchanged. |

## 3. Idempotency and moved tags

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_reprocessing_the_same_revision_is_idempotent` | The same repository and commit resolve to one snapshot, one stored row, and a new analysis id per run. |
| `test_a_moved_tag_does_not_overwrite_the_earlier_commit` | The same tag at a different commit produces a second snapshot, and the original commit is still stored under the tag. |

## 4. Incomplete and failed scans

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_missing_source_evidence_makes_the_snapshot_incomplete` | A release without source analysis is `incomplete` and names the missing input, instead of looking like a release with no calls. |
| `test_a_failed_scan_is_stored_as_failed_with_no_elements` | A failed run is stored as `failed` with no elements and an explanatory note. |

## 5. Isolation, chronology and evidence

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_repositories_stay_isolated` | Two repositories with the same tag and commit do not see each other's snapshots. |
| `test_history_is_ordered_by_release_date` | History is chronological even when releases are analyzed out of order. |
| `test_history_falls_back_to_commit_date_and_records_it` | A release without a publication date orders by commit date and says so. |
| `test_history_falls_back_to_the_analysis_timestamp` | With neither date, the analysis timestamp is used and labelled. |
| `test_source_evidence_corroborates_a_configured_relationship` | One edge carries both manifest and source evidence instead of becoming two edges. |
| `test_two_components_sharing_a_name_get_no_logical_identity` | A shared name yields no logical id, so two histories cannot be merged on a guess. |
| `test_heuristic_component_identity_is_labelled` | A heuristic name match is marked, not presented as direct evidence. |
| `test_unresolved_references_are_carried_onto_the_snapshot` | Unresolved and ambiguous references survive serialisation. |
| `test_snapshot_identity_is_deterministic_for_one_configuration` | The same release and configuration always produce the same snapshot id. |

## 6. Report and failure handling

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_reports_of_two_releases_do_not_overwrite_each_other` | Each report lives in its own snapshot directory and records that the store accepted it. |
| `test_a_refused_store_write_is_reported` | A refused graph write raises and the on-disk report says the store did not accept it. |
| `test_missing_required_upstream_artifact_is_an_input_error` | Missing component discovery or dependency resolution is rejected rather than turned into an empty architecture. |
| `test_release_metadata_carries_both_identities` | Release metadata keeps the repository id, release tag and resolved commit distinct. |

See
[`VALIDATION.md`](../../../app/components/architecture_recovery/graph_construction/VALIDATION.md)
for the two-release Online Boutique results and limitations.
