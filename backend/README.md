# Backend

Backend for the _Detection of Architectural Degradation during the Maintenance Phase_ research system.

> **Status:** in progress. Architecture recovery currently performs repository ingestion, repository inventory, manifest analysis, component discovery, dependency resolution, source code analysis and release-aware graph construction; database connectivity is wired up. Architecture extraction/validation/detection/scoring logic is not implemented yet.

## Structure

```
backend/
└── app/
    ├── api/                                      # HTTP/REST layer (FastAPI)
    ├── core/                                     # Cross-cutting application concerns
    ├── components/                               # Research components
    │   ├── architecture_recovery/
    │   │   ├── repository_ingestion/             # Clone/remove a repository in a local workspace
    │   │   ├── repository_inventory/             # Inventory a working tree into repository_inventory.json
    │   │   ├── manifest_analysis/                # Parse manifests into manifest_analysis.json
    │   │   ├── component_discovery/              # Identify components into component_discovery.json
    │   │   ├── dependency_resolution/            # Resolve relationships into dependency_resolution.json
    │   │   ├── source_code_analysis/             # Extract source-level calls into source_code_analysis.json
    │   │   └── graph_construction/               # Build version-scoped snapshots and publish them to Neo4j
    │   ├── architecture_validation/
    │   ├── architecture_degradation_detection/
    │   └── degradation_scoring/
    ├── domain/                                   # Domain models and shared research concepts
    ├── infrastructure/                           # Technical adapters (DB, git, external tools)
    └── shared/                                   # Shared utilities and helpers
```

The remaining research components are intentionally empty. Their internal subcomponents will be created in a later task.

Degradation detection (C3): install, one-command demo and CLI are in [`app/components/degradation_detection/README.md`](./app/components/degradation_detection/README.md).

## Endpoints

| Method | Path | Purpose |
| ------ | ---- | ------- |
| `GET` | `/` | API root: returns the service message and environment. |
| `GET` | `/health/postgres` | Checks PostgreSQL connectivity. |
| `GET` | `/health/neo4j` | Checks Neo4j connectivity. |
| `POST` | `/repositories` | Clones `{url, branch}` - with an optional `revision` to pin a tag - and returns the ingested record. Analysis is a separate call. |
| `POST` | `/repositories/releases` | Clones one explicit `{url, revision}` (tag or commit SHA) as its own checkout. Analysis is a separate call. |
| `POST` | `/repositories/{id}/recovery` | Runs architecture recovery over an ingested repository and returns one summary per stage. |
| `GET` | `/repositories/configurations` | Lists the snapshots configured for a pipeline run. |
| `POST` | `/repositories/configurations` | Saves `{url, branch, release_tag}`. Clones nothing. |
| `DELETE` | `/repositories/configurations/{id}` | Removes a configured snapshot. |
| `GET` | `/repositories` | Lists ingested repositories. |
| `GET` | `/repositories/{id}/snapshots` | Lists a repository's architecture snapshots, oldest first. |
| `GET` | `/repositories/{id}/snapshots/{snapshot_id}` | Returns one snapshot with its elements, relationships and evidence. |
| `GET` | `/repositories/{id}/snapshots/{snapshot_id}/details` | Joins that snapshot onto the recovery artifacts: discovery rules and artifacts, inventory files, resolution evidence, source findings, and any protocol the evidence establishes. |
| `GET` | `/repositories/{id}/snapshots/{snapshot_id}/recovery` | The stage-by-stage record of how that release was recovered: status, duration, counts, warnings and the artifact each stage wrote, plus what the artifacts now hold. |
| `DELETE` | `/repositories/{id}` | Removes an ingested repository from the machine. |

### Repository ingestion

The `repository_ingestion` subcomponent clones a repository into a temporary
workspace on the machine and removes it again. Each repository gets its own
directory below `REPOSITORIES_ROOT` (default `<system temp>/add-repositories`),
containing the working tree in `source/` and a `metadata.json` record.

Clone failures and invalid sources (`file://`, local paths, option-injection
attempts) are rejected before `git` runs; credentials embedded in a url are
redacted before anything is stored or returned. Re-ingesting the same url and
branch replaces the existing clone.

### Repository inventory

The `repository_inventory` subcomponent walks a working tree and writes a single
`repository_inventory.json` next to it (a sibling of `source/`, never inside it).
The document holds four collections: `files`, `classifications`, `components`
(candidate service boundaries) and `relationships`.

- **No contents are read** except a bounded subset: only files already
  classified as build or deployment manifests, and only up to a size cap. That
  is what turns a guessed boundary into a confirmed one.
- **Components are candidates.** A directory holding code without a build
  manifest is reported as `inferred`; an artifact that names a service yields
  `confirmed`. Directory proximity alone is never treated as proof.
- **Output is deterministic**, so inventories of two releases can be diffed to
  detect structural drift.
- Stages (scanning, classification, manifest inspection, component detection,
  relationship discovery, writing) are separate collaborators, each replaceable.

It runs as the first stage of recovery: `POST /repositories/{id}/recovery`
returns the clone together with an `inventory` summary, or `inventory_error`
when the inventory could not be produced. A failed inventory never fails or
rolls back the clone, because cloning is a separate, earlier operation.

To run it directly, for example after changing the classification rules:

```python
from app.components.architecture_recovery.repository_inventory import (
    RepositoryInventoryService,
)

# Returns the written path together with the inventory document.
path, inventory = RepositoryInventoryService().run_for_ingested(ingested_repository)
```

Configuration is split by sensitivity:

| File | Committed | Holds |
| ---- | --------- | ----- |
| [`backend/config.ini`](./config.ini) | yes | Non-sensitive tuning: scan and analysis limits, clone timeout, application name. |
| `backend/.env` | no | Secrets and environment-specific values: database hosts, credentials, workspace path. Start from [`.env.example`](./.env.example). |

Precedence, lowest to highest: the defaults in `app/core/config.py`, then
`config.ini`, then the environment and `.env`. So anything in the committed file
can be overridden per machine or per deployment, which is what CI and containers
should do.

Limits and extra exclusions are configured through the `[inventory]` and
`[manifest_analysis]` sections of `config.ini`.

### Manifest analysis

The `manifest_analysis` subcomponent parses the manifests the inventory found and
writes `manifest_analysis.json` beside `repository_inventory.json`. It runs
automatically after a successful inventory and its summary is included in the
`POST /repositories/{id}/recovery` response.

| Format | Analyzer | Extracted |
| ------ | -------- | --------- |
| Docker Compose | `compose` | services, images, build context, published/exposed ports, networks, volumes, environment, `depends_on`, secrets (names only) |
| Kubernetes | `kubernetes` | workloads, containers, images, ports, Service selectors, configured environment endpoints, ConfigMap/Secret references (names only), volume claims |
| Dockerfile | `dockerfile` | build stages, base images, exposed ports, runtime configuration, build inputs |
| OpenAPI / Swagger / AsyncAPI | `openapi` | API title and version, servers, paths, methods, operation ids |
| Protobuf | `protobuf` | package, services, RPCs, message types, imports |

It consumes an existing inventory and never traverses the repository itself, so
only files the inventory classified as a deployment manifest or an API
specification are opened. Analyzer selection is a registry, so a new format is a
new analyzer plus a registration, with no change to existing stages.

**Declarations are not runtime facts.** Every relationship carries an `origin`
that keeps them apart:

| Origin | Meaning |
| ------ | ------- |
| `declared_dependency` | the manifest says so (`depends_on`, a ConfigMap/Secret reference) |
| `declared_build_input` | a build input (image, build context, `COPY --from`) |
| `configured_endpoint` | a configured location (published port, server url, environment url) |
| `configured_filesystem` | a volume or claim mount |
| `api_definition` | an API surface (OpenAPI operation, protobuf RPC) |
| `verified_communication` | **reserved** — no analyzer may emit it; only a stage that observes real traffic can |

**Safety.** Secret and sensitive values are never recorded: only key names are,
with `values_extracted: false` on the resource. Environment values whose key
looks sensitive are redacted, and urls are stored without credentials. Manifests
are parsed with a safe loader that refuses arbitrary object tags, so a repository
cannot execute code through a manifest; nothing is executed or written back to
the working tree. Malformed files are recorded as failures or diagnostics rather
than silently dropped, and templated manifests (Helm) are reported as skipped
because they cannot be resolved without their template engine.

A per-test guide to this component's suite, explaining what each test attempts to
prove, is in
[`tests/components/architecture_recovery/test_manifest_analysis.md`](./tests/components/architecture_recovery/test_manifest_analysis.md).

### Component discovery

The `component_discovery` subcomponent identifies the logical architectural
components in a repository and associates the artifacts that belong to each.
It writes `component_discovery.json` beside the other artifacts and runs
automatically after manifest analysis.

An **artifact** is one repository file that describes or implements a component
(a deployment declaration, a build definition, a Dockerfile, an API contract).
A **component** is the logical unit those artifacts belong to. This distinction is
the point of the stage: a Compose service, its Dockerfile, its source project and
its API contract are four artifacts of *one* component, not four components.

| Evidence | Provides |
| -------- | -------- |
| manifest analysis | deployment declarations (Compose services, Kubernetes workloads) and API contracts |
| inventory | source projects (a directory holding a build manifest) and the files belonging to them |
| manifest analysis | Dockerfiles and their build stages |

Kubernetes `Service`, `ConfigMap` and `Secret` resources are **never** components.
A Service is attached to the workload its selector matched; the ConfigMap and
Secret remain the concern of manifest analysis.

**Identity resolution** is a union-find over identity keys (declared name plus
directory name), merged only by a named rule:

| Rule | Confidence | Meaning |
| ---- | ---------- | ------- |
| `build_context_containment` | direct | an artifact lies inside a declared Compose build context |
| `project_location_containment` | direct | an artifact lies inside a project root |
| `shared_image_reference` | direct | two deployments run the same application image |
| `name_and_location_match` | direct | names match and locations are related |
| `name_match` | heuristic | identity keys intersect without a location link |

A repository-root location is never treated as containment, and base images are
never identity evidence, so neither "everything is under the repository root" nor
"two Dockerfiles share `node:20`" can merge components. Two projects that share a
name but sit in unrelated directories are **not** merged; the conflict is reported
as a duplicate identity instead.

Component ids are a hash of the normalised name and canonical root path, so they
are stable across runs and independent of iteration order.

**Unresolved and ambiguous cases are preserved, never forced:**

- a Dockerfile, API contract or bare directory with no corroborating evidence is
  an `unresolved` artifact, not an invented component;
- a Service whose selector matches workloads in more than one component is an
  `ambiguous` association;
- components sharing a name but resolving to different identities are reported
  as duplicate identities.

Artifact associations are kept distinct: `deployed_as`, `defined_by`,
`built_from`, `implemented_by` and `contract_defined_by`. Every association and
every component carries the evidence that produced it, and a component's
confidence is the weakest link that holds it together.

### Dependency resolution

The `dependency_resolution` subcomponent correlates configured endpoints,
deployment declarations and Kubernetes resource mappings with the components and
artifacts established upstream. It writes `dependency_resolution.json` beside the
other artifacts and runs automatically after component discovery; its compact
summary is included in the `POST /repositories/{id}/recovery` response.

| Relationship type | Evidence |
| ----------------- | -------- |
| `configured_endpoint` | a configuration value names a known application component |
| `infrastructure_dependency` | a configured endpoint resolves to a component whose container image identifies a database, cache or message broker |
| `declared_dependency` | a Compose `depends_on` or `links` declaration |
| `resource_selection` | a Kubernetes Service selects a workload of a different component |

**Declarations are not communication.** A Compose `depends_on` entry, a Kubernetes
Service selector and an API contract each mean something different, and the
relationship type preserves that difference. No relationship claims verified
runtime traffic.

Resolution is conservative:

- a configured host resolves only through an exact deployment alias, a qualified
  Kubernetes name, or a normalised component name; the evidence records which;
- a host matching several components stays `ambiguous`, and one matching none
  stays `unresolved`, with its original endpoint preserved;
- exact duplicate evidence is aggregated, but different relationship types
  between the same pair are kept separate;
- source-code call evidence (SCIP or AST) is a reserved evidence source for a
  later stage. API contracts alone never create an edge.

See the Online Boutique validation report in
[`dependency_resolution/VALIDATION.md`](./app/components/architecture_recovery/dependency_resolution/VALIDATION.md).

### Source code analysis

The `source_code_analysis` subcomponent extracts source-level evidence of
inter-service calls and writes `source_code_analysis.json` beside the other
artifacts. It runs automatically after dependency resolution and adds a compact
summary to the `POST /repositories/{id}/recovery` response.

| Finding type | Source evidence |
| ------------ | --------------- |
| `grpc_service_call` | generated gRPC client construction and invocation |
| `http_service_call` | HTTP client invocation |
| `cache_client_usage` | Redis/cache client construction or operation |
| `database_client_usage` | database client construction or configuration |

Component identities come from component discovery. HTTP targets are resolved
through a literal host, a configured environment key already mapped by dependency
resolution, or the component's only configured endpoint. Cache and database
client usage resolves only when dependency resolution already identified a
matching infrastructure target.

Evidence strength is explicit: `observed_invocation` means a client construction
and an invocation were both found; `client_construction` means only the client
was constructed or configured; `symbol_reference` is reserved for weaker
symbol-only evidence. Static analysis never claims that a call executes at
runtime.

The stage is deliberately conservative:

- generated code, tests, vendored/build output and standalone client/example
  files are skipped before scanning;
- imports, shared generated code and Protobuf definitions never create edges;
- self-references are ignored;
- multiple call sites between the same pair are aggregated into one finding per
  finding type;
- unresolved and ambiguous targets are preserved instead of inventing a target;
- findings that corroborate a dependency-resolution relationship link to that
  relationship id rather than replacing the manifest evidence.

Supported languages are Go, Python, C#, JavaScript/TypeScript and Java. See the
Online Boutique validation report in
[`source_code_analysis/VALIDATION.md`](./app/components/architecture_recovery/source_code_analysis/VALIDATION.md).

### Graph construction and release history

The `graph_construction` subcomponent assembles the recovered evidence into one
**version-scoped architecture snapshot** per analyzed revision and publishes it
to Neo4j. It writes `architecture_graph_construction.json` under
`<repository-workspace>/graph_construction/<snapshot-id>/` and adds a compact
summary to the ingest response.

Release-aware analysis is explicit:

```http
POST /repositories
{ "url": "https://github.com/GoogleCloudPlatform/microservices-demo.git",
  "branch": "main", "revision": "v0.10.0" }

POST /repositories/{id}/recovery
```

Each analyzed revision gets its own workspace, so analyzing `v1.2.0` never
overwrites the checkout or the snapshot of `v1.0.0`. A tag is resolved to a
commit and both are recorded, because a tag can be moved.

| Identity | Meaning |
| -------- | ------- |
| `snapshot_id` | hash of repository id, resolved commit and analysis configuration; one revision has one snapshot |
| `analysis_id` | one execution of the pipeline; a rerun keeps the snapshot and records the new run |
| `logical_id` | the element's identity across releases, and only when its name is unique in that release |

The persistence rules:

- a new release creates a new snapshot; an earlier snapshot is never overwritten
  or deleted;
- rerunning one revision under the same configuration **reuses** its snapshot and
  replaces only that snapshot's own elements and edges;
- a moved tag produces a new snapshot because the commit, not the tag, is the
  key;
- repositories are isolated: every read and write is scoped by `repository_id`;
- `status` is `complete`, `incomplete` or `failed`, so a missing element in a
  failed scan is never read as a removed element;
- history orders by release date, then commit date, then analysis timestamp, and
  records which field placed the snapshot.

Snapshots are stored under `(:ArchitectureSnapshot)` / `(:ArchitectureElement)`,
separate from the validated graph's `(:Release)` / `(:Element)`, so recovery's
evidence and a validation rollup can never overwrite each other. No degradation
score is computed here.

A two-release validation against Online Boutique is in
[`graph_construction/VALIDATION.md`](./app/components/architecture_recovery/graph_construction/VALIDATION.md).

See the root [`ARCHITECTURE.md`](../ARCHITECTURE.md) for the intended future architecture.
