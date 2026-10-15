# Test Guide — Component Discovery

A quick-reference guide to [test_component_discovery.py](./test_component_discovery.py). Each entry
describes **what the test attempts to prove**, not just which function it calls.

- **Subject under test:** `app.components.architecture_recovery.component_discovery`
- **Scope:** 34 test functions across 12 sections, plus **5 API integration tests** in
  [`tests/api/test_repositories.py`](../../api/test_repositories.py) (section 12).
- **Fixtures:** 9 sample repositories under
  [`tests/fixtures/component_discovery/`](../../fixtures/component_discovery) — `simple_app`,
  `compose_service`, `k8s_workload_and_service`, `multi_service`, `source_only`,
  `orphan_artifacts`, `conflicting`, `ambiguous_service`, `sensitive`.
- **Run it:** `make test`, `cd backend && uv run pytest`, or target this file:
  `uv run pytest tests/components/architecture_recovery/test_component_discovery.py`

## Reading the tests

The suite is built around three ideas:

1. **Discovery is judged by what it produces.** Assertions inspect the *components*, their
   *artifacts*, the *association types* and the *merge rules* recorded as evidence — not merely
   that a report was produced.
2. **Incorrect merges matter as much as missed ones.** Every fixture is paired against a case
   where merging would be wrong: two projects sharing a name, a Dockerfile with no owner, a
   Service spanning two workloads. A suite that only proves *"the expected components appear"*
   would pass while happily collapsing unrelated services.
3. **Evidence is always traceable and never invented.** Every component and artifact must carry
   evidence with a confidence, every referenced artifact must exist, unresolved artifacts must
   carry a reason, and nothing sensitive may reach the serialised output.

Each fixture is run through the **real inventory and manifest analysis stages first**, so these
are end-to-end tests of the pipeline from a working tree — no network access or live clone needed.

### Shared helpers and fixtures

| Name | Purpose |
| ---- | ------- |
| `build(fixture)` | Runs inventory → manifest analysis → discovery over a fixture and returns the report. The single entry point every test uses. |
| `document(fixture)` | Returns the serialised (`to_dict()`) report, for assertions against the real JSON shape. |
| `component_named(payload, name)` | Returns the one component with that name, failing loudly (listing what *was* present) when absent. |
| `components_named(payload, name)` | Returns **all** components with a name — used where the point is that there are two. |
| `artifacts_of(payload, component)` | Resolves a component's `artifact_ids` into full artifact records. |
| `associations_of(payload, component)` | The set of association types a component actually uses, for exact-set comparisons. |
| `rules_of(component)` | The merge rules recorded in a component's evidence, so a test can assert *how* it was formed. |

---

## 1. A simple application: one deployment and one source project

Fixture: `simple_app` (a Kubernetes Deployment plus a Go project).

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_simple_app_is_one_component` | A Deployment and the source project it points at resolve to **one** component named `orders`, typed `service`, rooted at `services/orders`, with the language carried over from the inventory. |
| `test_simple_app_associates_all_three_artifacts` | The same component uses all three association types and roles — `deployed_as`, `implemented_by`, `defined_by` — proving artifacts stay distinct while belonging to one component. |

---

## 2. A Compose service with a Dockerfile and build context

Fixture: `compose_service` (Compose service → `./web` build context → Dockerfile + Node project).

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_compose_service_dockerfile_project_and_manifest_are_one_component` | The whole chain — Compose service, Dockerfile, project manifest and source — is **one** component with 4 artifacts, not four components. This is the central claim of the stage. |
| `test_compose_build_context_is_direct_evidence` | The merge is attributed to the `build_context_containment` rule and the component is `direct` confidence — a declared build context is strong evidence, not a guess. |
| `test_dockerfile_records_its_build_stages` | Multi-stage builds survive into discovery: both stage names and the stage count are recorded, and base images (`node:20`) are *carried* on the artifact while never being treated as identity evidence. |

---

## 3. Kubernetes workloads and their Services

Fixture: `k8s_workload_and_service` (one workload, two Services, one ConfigMap).

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_kubernetes_service_does_not_become_a_component` | A Kubernetes `Service` never inflates the component count: the repository yields exactly one component. |
| `test_kubernetes_services_attach_to_their_workload` | Both Services attach to the workload component as *artifacts*, and the ConfigMap does **not** become a component — neither appears in the component name set. |
| `test_attached_service_evidence_explains_why` | The attachment is explained in prose evidence ("exposes this component's workload"), so a reader can tell why a Service belongs to that component. |

---

## 4. A repository containing multiple services

Fixture: `multi_service` (Python API, Go worker, image-only cache, one Compose file).

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_multiple_services_are_discovered_separately` | Three services in one repository are found as exactly three components — directory proximity alone does not fuse them into a monolith. |
| `test_multi_service_keeps_languages_apart` | The polyglot case works: `api` is Python, `worker` is Go — no assumption that a repository is single-language. |
| `test_image_only_service_has_no_location` | A service built from a registry image (`cache`) is still a component, but `root_path` is `None` — the model does not invent a source location that does not exist. |

---

## 5. Source projects with no deployment manifests

Fixture: `source_only` (Go and Node projects, no manifests).

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_source_only_repository_yields_applications` | With no deployment to cite, components are typed `application` rather than `service`, both are `direct`, and they use only `implemented_by` / `defined_by` — the type reflects the evidence available. |

---

## 6. Artifacts whose component identity cannot be determined

Fixture: `orphan_artifacts` (a Dockerfile, a `.proto` and an OpenAPI file, all unowned).

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_orphan_artifacts_are_unresolved_not_invented_as_components` | Three unattributable artifacts produce **zero** components and three `unresolved` entries of the right kinds — the stage refuses to fabricate components from a lone artifact. |
| `test_unresolved_artifacts_carry_a_reason` | Each unresolved entry carries a reason and evidence, so the gap is explainable rather than just absent. |

---

## 7. Conflicting and ambiguous evidence

Fixtures: `conflicting` (two `frontend` projects, an unrelated Dockerfile) and `ambiguous_service`
(one Service selecting two workloads).

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_same_name_in_unrelated_locations_is_not_merged` | A shared name is **not** sufficient: two `frontend` projects under unrelated directories stay two components with the right roots. This is the guarded counterpart to the name-based rules. |
| `test_duplicate_identity_is_reported` | The conflict is surfaced, not hidden: one duplicate identity and one ambiguity are counted, and the ambiguity lists **both** candidate component ids. |
| `test_unrelated_dockerfile_stays_unresolved` | A Dockerfile that cannot be attributed remains unresolved (`shared/Dockerfile`) instead of being attached to the nearest project. |
| `test_selector_matching_two_workloads_is_ambiguous` | A Service whose selector spans two components is reported as a `kubernetes_service` ambiguity with two candidates — it is not silently attached to one of them. |

---

## 8. Sensitive values

Fixture: `sensitive` (Compose with passwords, tokens and a credentialed URL).

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_sensitive_values_never_reach_the_output` | No known secret (`supersecret`, `tokenvalue123`, `******db:5432/app`) appears anywhere in the serialised report — discovery does not reintroduce what manifest analysis redacted. |
| `test_sensitive_repository_details_are_still_discovered` | Redaction costs nothing structurally: the same repository still yields its component with all 4 artifacts. |

---

## 9. Determinism, identity and evidence integrity

The properties that make two releases' artifacts diffable.

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_output_is_deterministic_across_runs` | *(4 fixtures)* Two runs over the same tree are byte-identical once `generated_at` is removed — so a later release's artifact can be compared against an earlier one. |
| `test_identifiers_are_stable_and_content_addressed` | Component ids are unique and prefixed `component:`; artifact ids are prefixed `artifact:` — ids are derived from content, not iteration order or sequence numbers. |
| `test_every_referenced_artifact_exists_and_is_owned_once` | Every id in a component's `artifact_ids` resolves to a real artifact, and no artifact is claimed by two components — ownership is exclusive. |
| `test_every_component_and_artifact_carries_evidence` | Every component and every artifact has evidence, and each artifact's confidence is one of `direct` / `heuristic` — findings are always explainable and never arbitrary numbers. |

---

## 10. Missing or malformed upstream artifacts

The stage fails loudly on bad input, and degrades gracefully on partial input.

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_missing_inventory_is_an_input_error` | Running the disk entry point with no inventory raises `DiscoveryInputError` — it does not silently discover nothing. |
| `test_malformed_inventory_is_an_input_error` | Corrupt inventory JSON raises `DiscoveryInputError`. |
| `test_malformed_manifest_analysis_is_an_input_error` | A structurally wrong analysis report raises `AnalysisArtifactError` from the loader. |
| `test_missing_manifest_analysis_is_an_input_error` | An absent analysis file raises `AnalysisArtifactError`. |
| `test_one_bad_manifest_does_not_lose_the_other_components` | A repository containing an ambiguous/unparseable element still yields its 2 valid components and reports the 1 ambiguity — one bad file cannot void the run. |

---

## 11. Output artifact and loaders

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_writer_produces_one_versioned_artifact` | Exactly one file (`COMPONENT_DISCOVERY_FILE_NAME`) is written, carrying the schema version (`1.0.0`), generator name, repository id and the identity policy actually used. |
| `test_writer_replaces_an_existing_report` | Re-running overwrites in place — one file, same path, no litter. |
| `test_run_for_ingested_reads_the_upstream_artifacts` | The disk path agrees with the in-memory path: given only the workspace the previous stages wrote, discovery reconstructs the same components, and writes its report as a **sibling** of the working tree, never inside it. |

---

## 12. Evidence integrity, summary and API integration

The last two tests close the loop on the module's own guarantees; the API tests prove the stage is
wired into the ingest pipeline without disturbing it.

| Test | What it attempts to prove |
| ---- | ------------------------- |
| `test_no_component_is_derived_from_a_name_alone` | Restates the central guard from the other direction: a contract whose name matches nothing must produce no component at all. |
| `test_summary_counts_agree_with_the_collections` | *(3 fixtures)* Every summary counter matches its collection, and `direct_association_count` is recomputed from the artifacts — the summary cannot drift from the data. |
| `test_ingesting_a_repository_discovers_components` | The `POST /repositories` flow runs discovery automatically and reports counts, with the artifact written **beside** the clone rather than inside it. |
| `test_previous_response_fields_are_unchanged` | Adding this stage left the earlier stages' response fields intact (ingestion, inventory, manifest analysis). |
| `test_discovery_is_skipped_when_analysis_fails` | Discovery declares its missing prerequisite ("no manifest analysis") instead of guessing from partial input. |
| `test_discovery_is_skipped_when_the_inventory_fails` | Likewise when the inventory is missing ("no repository inventory"). |
| `test_discovery_failure_does_not_fail_the_ingest` | A discovery failure leaves the clone and earlier stages intact and still returns `201` — the pipeline isolates each stage's failure. |
