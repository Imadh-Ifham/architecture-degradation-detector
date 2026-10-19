# Test Guide — Manifest Analysis

A quick-reference guide to [test_manifest_analysis.py](./test_manifest_analysis.py). Each entry
describes **what the test attempts to prove**, not just which function it calls.

- **Subject under test:** `app.components.architecture_recovery.manifest_analysis`
- **Scope:** 84 test functions across 9 sections, expanding to **117 collected cases** once
  parametrisation is counted.
- **Fixtures:** files under [`tests/fixtures/manifest_analysis/`](../../fixtures/manifest_analysis)
  (`compose/`, `kubernetes/`, `dockerfile/`, `api/`, `proto/`, `unsupported/`).
- **Run it:** `make test`, `cd backend && uv run pytest`, or target this file:
  `uv run pytest tests/components/architecture_recovery/test_manifest_analysis.py`

## Reading the tests

The suite is built around three ideas:

1. **Extract, don't just parse.** Assertions check the *resources*, *relationships*, *endpoints*
   and *references* that came out — not merely that a file loaded.
2. **Declarations are not runtime facts.** Every relationship carries an `origin`
   (`declared_dependency`, `configured_endpoint`, `api_definition`, …) and the suite asserts
   `verified_communication` is **never** emitted.
3. **Nothing sensitive leaks, nothing executes.** Secret/credential values must not appear in the
   serialised output, and untrusted manifests must not be able to run code.

### Shared helpers and fixtures

| Name | Purpose |
| ---- | ------- |
| `classify(path)` | Builds a `FileRecord` exactly as the inventory stage would, so analyzers get realistic input. |
| `analyze(analyzer, path)` | Runs one analyzer over one fixture file. |
| `resource_named(result, name, kind)` | Returns the resource with that name/kind, failing loudly (listing what *was* present) when absent. |
| `relationships_of(result, type)` | Filters a result's relationships by `RelationshipType`. |
| `reference_named(result, name)` | Returns a reference by name, failing loudly when absent. |
| `serialized(result)` | JSON-dumps every collection of a result — used for leak checks. |
| `compose_result` | Fixture: `ComposeAnalyzer` over `compose/valid-compose.yaml`. |
| `kubernetes_result` | Fixture: `KubernetesAnalyzer` over `kubernetes/multi-document.yaml`. |
| `dockerfile_result` | Fixture: `DockerfileAnalyzer` over `dockerfile/Dockerfile`. |
| `openapi_result` | Fixture: `OpenApiAnalyzer` over `api/openapi-cart.yaml`. |
| `protobuf_result` | Fixture: `ProtobufAnalyzer` over `proto/cart.proto`. |
| `build_inventory(root)` | Runs the real `RepositoryInventoryService` over a tree, feeding the service tests an authentic inventory. |

---

## 1. Analyzer selection

How the registry decides which analyzer owns a file.

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_registry_selects_the_right_analyzer` | *(parametrised over 8 paths)* Each of compose (valid + minimal), kubernetes (multi-doc + no-kind), Dockerfile, OpenAPI (yaml + json) and protobuf routes to the correctly-named analyzer. |
| `test_registry_offers_compose_before_kubernetes` | Both are YAML deployment manifests, so **ordering** is what protects Compose: `compose` must be listed before `kubernetes`. |
| `test_compose_wins_over_the_permissive_kubernetes_fallback` | The Kubernetes analyzer's `can_analyze` is deliberately a catch-all that would also accept a Compose file; the Compose file is still parsed as Compose purely because the registry offers Compose first. |
| `test_source_and_configuration_files_are_not_candidates` | Kubernetes manifests and protobuf files are candidates; infrastructure config such as `.tf` is out of scope for this stage (documented in the comment, not asserted). |

---

## 2. Docker Compose

Analyzer: `ComposeAnalyzer` against `compose/valid-compose.yaml`.

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_compose_declares_its_services` | The file parses (`PARSED`) and the `web` service resource carries its `container_name` (`web-app`). |
| `test_compose_records_images_and_build_inputs` | The `example/web` image resource exists, both `USES_IMAGE` relationships have origin `declared_build_input`, and the out-of-file build context (`./web`) and `Dockerfile` stay **unresolved references** (`compose_build_dockerfile`) instead of guessed relationships. |
| `test_compose_distinguishes_published_from_exposed_ports` | `PUBLISHES_PORT` (host-facing, 2) is kept separate from `EXPOSES_PORT` (container-facing, 1), and endpoints preserve host/port/protocol — including a loopback host and a UDP port. |
| `test_compose_records_networks_including_external` | Both networks become resources with a correct `external` flag, and all 3 `JOINS_NETWORK` links carry origin `configured_endpoint`. |
| `test_compose_records_volumes_and_bind_mounts` | Named volumes become resources (`external` flag preserved); the host path is *not* a volume resource. Both `MOUNTS_VOLUME` links are `configured_filesystem`, and the bind mount is recorded as a `compose_bind_mount` reference. |
| `test_compose_redacts_sensitive_environment_values` | `DB_PASSWORD` is redacted with **no `value` key at all**, while non-sensitive keys keep their values — and the raw secret (`hunter2`) is absent from the serialised result. |
| `test_compose_turns_environment_urls_into_configured_endpoints` | A URL in an environment variable is promoted to a `environment`-scope endpoint with the right host, port and scheme (`db:5432` / `postgres`). |
| `test_compose_links_a_configured_endpoint_to_its_service` | Because host `db` is a *declared* service, the `REFERS_TO_SERVICE` link resolves to that service's id (origin `configured_endpoint`). |
| `test_compose_records_declared_dependencies` | `DEPENDS_ON` links are all `declared_dependency`; only the declared service resolves, the unknown one does not, and evidence retains the condition (`service_healthy`). |
| `test_compose_records_secret_references_without_values` | A secret is recorded with `values_extracted: false` and its `external` flag, plus exactly one `REFERENCES_SECRET` link — **names only, never values**. |
| `test_compose_reports_line_numbers` | Resources carry a usable source location (line 2, relative path) for provenance. |
| `test_compose_minimal_file_parses_with_missing_optional_fields` | A minimal Compose file still parses cleanly with no spurious diagnostics. |
| `test_compose_malformed_file_fails_without_raising` | Bad YAML yields `FAILED` with a line number and **no exception**, so one bad file can't abort the run. |

---

## 3. Kubernetes

Analyzer: `KubernetesAnalyzer` against `kubernetes/multi-document.yaml` (plus focused fixtures).

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_kubernetes_reads_every_document` | All documents in a multi-document file are read, yielding workloads, services, ConfigMaps, Secrets, volumes and containers. |
| `test_kubernetes_records_namespace_and_workload_details` | Workload resources keep their namespace and meaningful attributes (`kind`, pod labels). |
| `test_kubernetes_records_container_images_and_ports` | Containers link to their workload, images keep the full reference (`…:1.2.3`), and container-scope endpoints record the port. |
| `test_kubernetes_matches_a_service_selector_to_its_workload` | A Service selector that matches a workload produces exactly one `SELECTS_WORKLOAD` link in the right direction (service → workload). |
| `test_kubernetes_reports_a_selector_that_matches_nothing` | An unmatched selector is **recorded as a diagnostic**, not silently converted into a relationship or treated as an error. |
| `test_kubernetes_resolves_config_and_secret_references` | Declared ConfigMap/Secret references resolve; a reference to an undeclared Secret stays unresolved with an explicit reason. |
| `test_kubernetes_records_volume_claim_as_a_mount` | A volume claim becomes a resolved `MOUNTS_VOLUME` (`configured_filesystem`) plus a resolved reference. |
| `test_kubernetes_never_exposes_config_map_or_secret_values` | Only **key names** are stored, `values_extracted` is `false`, secret type is retained, and none of the raw/base64/plaintext secret values appear in serialised output. |
| `test_kubernetes_redacts_sensitive_container_environment` | Environment entries distinguish literal values from `from_secret` / `from_config_map` sources — including a reference to an undeclared secret. |
| `test_kubernetes_turns_environment_addresses_into_configured_endpoints` | A literal environment value shaped like `host:port` or a URL becomes an `environment` endpoint and a `REFERS_TO_SERVICE` relationship with `configured_endpoint` origin; non-endpoint values and sensitive values stay out. |
| `test_kubernetes_reads_containers_nested_in_a_cronjob` | Container discovery is not hard-coded to Deployments; it reaches containers nested under a CronJob. |
| `test_kubernetes_reports_an_unsupported_kind` | An unsupported kind (Ingress) is reported as a diagnostic and produces **no** resource. |
| `test_kubernetes_document_without_a_kind_is_reported` | A document missing `kind` degrades to `PARTIAL` with a clear diagnostic instead of failing the file. |
| `test_kubernetes_malformed_file_fails_without_raising` | Broken YAML yields `FAILED` with an error-severity diagnostic, without raising. |
| `test_templated_manifest_is_skipped_not_failed` | A Helm template is not malformed — it is `SKIPPED`, produces no resources, and explains that templated manifests cannot be parsed. |
| `test_template_expression_detection_ignores_shell_style_variables` | `{{ … }}` means templated, but Compose interpolation `${VAR}` does not — preventing false "templated" skips. |

---

## 4. Dockerfile

Analyzer: `DockerfileAnalyzer` against `dockerfile/Dockerfile`.

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_dockerfile_records_every_build_stage` | Multi-stage builds yield one `BUILD_STAGE` per stage, in order, each with its base image. |
| `test_dockerfile_links_stages_to_their_base_images` | `BUILDS_FROM` links (origin `declared_build_input`) point at both base images **and** at an earlier stage, i.e. stage-on-stage builds are modelled. |
| `test_dockerfile_resolves_copy_from_stage` | `COPY --from` resolves against declared stages and yields an explicit unresolved reference when the stage name is wrong. |
| `test_dockerfile_records_exposed_ports` | `EXPOSE` becomes endpoints with the correct protocol, including a non-TCP port. |
| `test_dockerfile_redacts_sensitive_environment_values` | `ENV` secrets are redacted (no `value` key) while ordinary values survive; the raw secret never reaches the output. |
| `test_dockerfile_handles_continuation_lines` | A multi-line `ENV` block (backslash continuations) is parsed as a whole — all three variables are captured. |
| `test_dockerfile_recognises_an_environment_endpoint` | A registry host in build configuration becomes a `build_configuration`-scope endpoint. |
| `test_dockerfile_records_runtime_configuration` | `ENTRYPOINT`, `CMD`, `USER` and `HEALTHCHECK` are all recorded on the stage. |
| `test_dockerfile_records_copied_build_inputs` | Every `COPY` source (files, `.`, nested paths) is recorded as a `dockerfile_copy_source` reference, and all are unresolved because the content lives outside the Dockerfile. |
| `test_dockerfile_links_to_the_inventory_component` | When the inventory assigns a `component_id`, the analyzer propagates it onto the stage resource — connecting the manifest layer to the component layer. |
| `test_dockerfile_without_from_is_partial` | A Dockerfile with no `FROM` yields `PARTIAL`, no fabricated resources and (currently) no diagnostics. |

---

## 5. OpenAPI

Analyzer: `OpenApiAnalyzer` against `api/openapi-cart.yaml` (plus JSON and negative fixtures).

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_openapi_records_the_api_identity` | The API resource captures title, version and the detected specification (OpenAPI 3.0.0). |
| `test_openapi_records_servers_as_configured_endpoints` | Servers become `base_url` endpoints: a concrete URL resolves to host/port/scheme (443/https), while a *templated* URL has no host — and its `SERVES_AT` link is therefore not resolved. All links are origin `configured_endpoint`. |
| `test_openapi_records_operations_with_their_methods` | Each HTTP method becomes an `API_OPERATION` with method/path/tags/deprecated, and a path-level `parameters` key is **not** mistaken for a verb. |
| `test_openapi_operations_are_api_definitions` | `DEFINES_OPERATION` links (origin `api_definition`) connect the API to each of its operations. |
| `test_openapi_reports_line_numbers` | YAML input yields real source positions. |
| `test_openapi_json_specification_is_supported` | A JSON spec parses with `ExtractionMethod.JSON`, and since JSON has no positions, `line` is `None` rather than fabricated. |
| `test_openapi_malformed_json_fails_without_raising` | Invalid JSON yields `FAILED` with a location, without raising. |
| `test_openapi_file_that_is_not_a_specification_is_partial` | A JSON/YAML file that isn't a spec degrades to `PARTIAL` with an explanatory diagnostic. |

---

## 6. Protobuf

Analyzer: `ProtobufAnalyzer` against `proto/cart.proto`.

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_protobuf_records_package_and_syntax` | The package resource captures the declared syntax (`proto3`). |
| `test_protobuf_records_services_and_their_rpcs` | Both services are found and 4 RPCs are linked via `DEFINES_RPC` (origin `api_definition`). |
| `test_protobuf_attributes_rpcs_to_the_enclosing_service` | Scope tracking is correct: an RPC after the second `service` block belongs to *that* service and does not leak into a neighbouring block. |
| `test_protobuf_links_rpc_request_and_response_types` | Request/response types are linked; locally declared types resolve (7) while the imported `google.protobuf.Empty` does not (1 unresolved). |
| `test_protobuf_records_messages_and_enums` | Declared messages are recorded — and an enum (`CartStatus`) is surfaced under the same `PROTO_MESSAGE` kind, since there is no separate enum kind. |
| `test_protobuf_records_an_import_as_an_unresolved_reference` | An `import` becomes a `protobuf_import` reference that is unresolved, because the file is not analysed here. |
| `test_protobuf_strips_comments_and_keeps_line_numbers` | Comment stripping does not shift reported line numbers (the service is still reported at its true line). |
| `test_protobuf_without_declarations_is_partial` | A `.proto` with nothing recognisable yields `PARTIAL` with diagnostics rather than a silent empty result. |

---

## 7. Redaction and parsing helpers

Unit-level checks of the safety primitives the analyzers rely on.

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_sensitive_keys_are_recognised` | *(10 keys)* Passwords, API keys, secrets, tokens, private keys and `Authorization` are all detected as sensitive. |
| `test_non_sensitive_keys_are_not_over_redacted` | *(6 keys)* Lookalikes are **not** over-redacted — `DATABASE_URL`, `AUTHOR`, `AUTHORS_FILE`, `REGION`, `PORT`, `LOG_LEVEL` keep their values. |
| `test_sanitize_scalar_redacts_by_key` | A sensitive key redacts the value outright (`value is None`, `redacted True`). |
| `test_sanitize_scalar_strips_url_credentials` | Embedding credentials in a URL is stripped while the resolvable origin is kept, so usernames/passwords never survive. |
| `test_sanitize_url_keeps_only_the_origin` | Query strings and paths are discarded; only scheme+host remains. |
| `test_endpoint_candidates_are_extracted` | *(5 values)* `http`, `https`, `grpc`, `redis` URLs and a bare `host:port` all yield the right host/port/scheme (with the scheme-aware default port). |
| `test_non_endpoint_values_are_not_mistaken_for_endpoints` | *(6 values)* Plain text, image tags, file paths, empties — and a credential-bearing URL — are **not** treated as endpoints (avoids leaking a URL that is itself secret). |
| `test_compose_port_forms_parse` | *(4 forms)* Short syntax variants (`8080:80`, `ip:host:container/udp`, bare port, port ranges) all normalise to host/container port + protocol. |
| `test_compose_port_long_form_parses` | The mapping (long) syntax normalises to the same shape as the short syntax. |

---

## 8. YAML safety

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_yaml_loader_refuses_arbitrary_python_objects` | A manifest using `!!python/object/apply` cannot execute code: the loader reports an error and returns no documents. |
| `test_yaml_loader_reports_multi_document_lines` | Each document in a multi-document stream keeps its own starting line, so diagnostics and provenance stay accurate. |

---

## 9. Analysis service and writer

End-to-end behaviour over the whole fixture tree, using the real inventory stage.

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_service_analyzes_only_manifest_files` | Source code, docs and `.tf` files are never opened; only the manifest (`Dockerfile`) is analysed. |
| `test_service_reports_a_manifest_no_analyzer_supports` | An unsupported file is `SKIPPED` with `analyzer is None`, a clear diagnostic, and it is counted in `summary.skipped_count`. |
| `test_service_produces_a_consistent_summary` | Summary counters match the actual collections, all five analyzers contribute, and `analyzed + skipped + failed == file_count` — the report cannot silently drop files. |
| `test_service_output_is_deterministic` | Two runs over the same inventory produce byte-identical output (ignoring the timestamp), so two releases can be diffed. |
| `test_service_never_asserts_verified_communication` | The strongest safety invariant: no relationship claims `verified_communication`; only declaration/configuration/definition origins appear. |
| `test_service_keeps_no_secret_material_in_the_report` | No known secret value appears anywhere in the serialised report. |
| `test_service_reports_evidence_for_every_finding` | Every resource and relationship carries evidence with a method and a source path — findings are always traceable. |
| `test_writer_produces_a_single_versioned_file` | The writer emits exactly one file (`MANIFEST_ANALYSIS_FILE_NAME`) with the expected schema version, generator name and repository id. |
| `test_writer_replaces_an_existing_report_atomically` | Re-running replaces the report in place — one file, same path, no litter. |
| `test_run_for_ingested_reads_the_existing_inventory` | The pipeline entry point reuses the inventory the previous stage wrote (rather than re-walking the tree) and writes its report as a *sibling* of the working tree, never inside it. |
| `test_run_for_ingested_requires_an_inventory` | Running without a prior inventory raises `AnalysisInputError` — the stage fails loudly instead of analysing a missing input. |
| `test_load_inventory_rejects_a_malformed_inventory` | Corrupt JSON raises `AnalysisInputError`. |
| `test_load_inventory_rejects_an_unexpected_structure` | Structurally wrong JSON (missing required fields) raises `AnalysisInputError`. |
| `test_analysis_respects_the_file_size_limit` | With a tiny `max_bytes`, oversized files are `SKIPPED` with an "analysis limit" diagnostic, proving the size cap is enforced. |
