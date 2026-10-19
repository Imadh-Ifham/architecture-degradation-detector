# Test Guide — Dependency Resolution

A quick-reference guide to
[test_dependency_resolution.py](./test_dependency_resolution.py). Each entry
describes **what the test attempts to prove**, not just which function it calls.

- **Subject under test:** `app.components.architecture_recovery.dependency_resolution`
- **Scope:** 20 test functions, plus API integration tests in
  [`tests/api/test_repositories.py`](../../api/test_repositories.py).
- **Fixtures:** 4 sample repositories under
  [`tests/fixtures/dependency_resolution/`](../../fixtures/dependency_resolution)
  — `compose_app`, `k8s_app`, `ambiguous_target`, `shared_contracts`.
- **Run it:** `cd backend && uv run pytest
  tests/components/architecture_recovery/test_dependency_resolution.py`

Each fixture is run through the **real inventory, manifest analysis and component
discovery stages first**, so the tests exercise the same evidence the application
produces. No network access or live clone is required.

## Shared helpers

| Name | Purpose |
| ---- | ------- |
| `build_pipeline(fixture)` | Runs inventory → manifest analysis → component discovery → dependency resolution and returns every stage's result. |
| `build_report(fixture)` | Returns only the dependency resolution report. |
| `relationship(report, type, source, target)` | Returns one resolved relationship, failing loudly with the actual edges when absent. |

---

## 1. Resolution and infrastructure

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_configured_endpoint_resolves_to_a_known_component` | An explicit `*_SERVICE_ADDR` value resolves to the component that declares the matching deployment name, with `declared` confidence. |
| `test_hostname_and_port_are_preserved_in_evidence` | Both a bare `host:port` and a URL endpoint survive into the provenance exactly as configured. |
| `test_port_disambiguates_two_candidate_components` | When a hostname matches two components, a unique matching declared port selects one and the method is recorded. |
| `test_infrastructure_endpoint_resolves_to_a_cache_target` | A Redis address resolves to the Redis component and is classified `infrastructure` / `cache` from its container image. |

## 2. Preserving uncertainty

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_unresolved_hostname_is_preserved` | An unknown host stays an `unresolved` candidate with its host, port and original endpoint. |
| `test_endpoint_matching_multiple_candidates_is_ambiguous` | Two components sharing a name produce no relationship; both candidate ids are preserved on one `ambiguous` candidate. |

## 3. Negative tests: declarations and contracts are not communication

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_compose_startup_dependency_is_not_application_communication` | `depends_on` becomes a `declared_dependency`, never `verified_communication`. |
| `test_kubernetes_service_selection_is_not_an_application_dependency` | A Service selector targeting its own workload creates no self-edge or `resource_selection`; configured endpoints still resolve. |
| `test_dockerfile_build_time_endpoint_is_not_a_runtime_dependency` | A Dockerfile `ENV` endpoint does not become a component dependency. |
| `test_shared_protobuf_messages_do_not_create_cross_component_edges` | A shared Protobuf message/service produces no relationship between the components that share it. |

## 4. Aggregation and type preservation

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_multiple_evidence_sources_are_aggregated` | Two environment references to the same target aggregate into one relationship with both keys and component-discovery evidence; duplicates are counted. |
| `test_different_relationship_types_are_preserved_between_the_same_pair` | A configured endpoint and a declared startup dependency between the same pair remain two relationships. |

## 5. Upstream failure handling

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_missing_upstream_artifacts_raise_an_input_error` | A missing `component_discovery.json` is an input error with a clear message. |
| `test_malformed_component_discovery_raises_an_input_error` | Malformed JSON is rejected rather than producing an empty graph. |
| `test_missing_manifest_analysis_raises_an_input_error` | A missing `manifest_analysis.json` is reported before resolution starts. |
| `test_component_document_without_components_raises_an_input_error` | A structurally incomplete component document is rejected with the expected shape named. |

## 6. Safety, determinism and persistence

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_sensitive_values_are_not_leaked` | Passwords and credentials embedded in a URL never reach any relationship or candidate; the sanitized endpoint is preserved. |
| `test_repeated_runs_produce_deterministic_output` | Two runs over the same inputs produce identical output apart from `generated_at`. |
| `test_run_for_ingested_reuses_the_written_upstream_artifacts` | The stage can read the existing artifacts from disk without re-running upstream stages. |
| `test_report_is_written_beside_the_upstream_artifacts` | `dependency_resolution.json` lands in the analysis workspace and its summary matches the relationships actually written. |

See
[`VALIDATION.md`](../../../app/components/architecture_recovery/dependency_resolution/VALIDATION.md)
for the Online Boutique validation results and limitations.
