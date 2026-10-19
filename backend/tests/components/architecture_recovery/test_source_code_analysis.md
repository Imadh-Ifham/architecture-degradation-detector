# Test Guide — Source Code Analysis

A quick-reference guide to
[test_source_code_analysis.py](./test_source_code_analysis.py). Each entry
describes **what the test attempts to prove**, not just which function it calls.

- **Subject under test:** `app.components.architecture_recovery.source_code_analysis`
- **Scope:** 19 test functions, plus API integration tests in
  [`tests/api/test_repositories.py`](../../api/test_repositories.py).
- **Fixtures:** 4 sample repositories under
  [`tests/fixtures/source_code_analysis/`](../../fixtures/source_code_analysis)
  — `go_grpc`, `http_app`, `csharp_cache`, `ambiguous_target`.
- **Run it:** `cd backend && uv run pytest
  tests/components/architecture_recovery/test_source_code_analysis.py`

Each fixture is run through the **real inventory, manifest analysis, component
discovery and dependency resolution stages first**, so the tests exercise the
same evidence the application produces. No network access or live clone is
required.

## 1. Go gRPC evidence

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_go_grpc_invocation_resolves_to_a_component` | A generated `NewXClient(...).Method(...)` call resolves to the component named by the client type, with `observed_invocation` strength. |
| `test_generated_and_standalone_client_files_are_skipped` | Generated `.pb.go` files and standalone `client.py` files do not create duplicate or self-referential findings. |
| `test_imports_do_not_create_findings` | Importing a generated package without constructing or invoking a client produces no finding. |
| `test_unresolved_service_name_is_preserved` | A client type with no matching component stays an unresolved candidate with its original reference. |

## 2. HTTP evidence

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_http_call_resolves_through_a_configured_environment_key` | An HTTP call whose URL expression references a field mapped to `SHOPPING_ASSISTANT_SERVICE_ADDR` resolves through dependency resolution. |
| `test_http_call_resolves_through_the_only_configured_endpoint` | A Locust `self.client.get(...)` call with a literal path resolves to the component's only configured endpoint. |
| `test_literal_unknown_host_is_not_resolved_to_the_only_endpoint` | A literal host that matches no component stays unresolved instead of being forced onto the component's only configured endpoint. |

## 3. Cache evidence and negative matching

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_cache_client_usage_resolves_to_an_infrastructure_target` | C# `AddStackExchangeRedisCache` plus `IDistributedCache.GetAsync/SetAsync` resolves to the cache target identified by dependency resolution. |
| `test_cache_operations_are_not_mistaken_for_http_calls` | `GetAsync` on an `IDistributedCache` is not reported as an HTTP call. |

## 4. Ambiguity, aggregation and corroboration

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_ambiguous_service_name_is_preserved` | Two components sharing a service alias produce one ambiguous candidate and no finding. |
| `test_multiple_call_sites_are_aggregated` | Multiple HTTP call sites between the same pair produce one finding with all evidence entries. |
| `test_findings_corroborate_dependency_resolution_relationships` | A source finding that matches a dependency-resolution pair links to that relationship id and contributes to `corroborated_count`. |

## 5. Safety, determinism and persistence

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_sensitive_source_text_is_not_leaked` | Source text containing a secret is never copied into the report. |
| `test_repeated_runs_produce_deterministic_output` | Two runs over the same inputs produce identical output apart from `generated_at`. |
| `test_report_is_written_beside_the_upstream_artifacts` | `source_code_analysis.json` lands in the analysis workspace and its summary matches the findings written. |

## 6. Upstream failure handling

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_missing_inventory_raises_an_input_error` | A missing inventory is rejected before analysis starts. |
| `test_missing_component_discovery_raises_an_input_error` | A missing `component_discovery.json` is reported with a clear message. |
| `test_missing_dependency_resolution_raises_an_input_error` | A missing `dependency_resolution.json` is reported before scanning. |
| `test_run_for_ingested_reuses_the_written_upstream_artifacts` | The stage can read existing artifacts from disk without re-running upstream stages. |

See
[`VALIDATION.md`](../../../app/components/architecture_recovery/source_code_analysis/VALIDATION.md)
for the Online Boutique validation results and limitations.
