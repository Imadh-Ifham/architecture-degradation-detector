# Backend

Backend for the _Detection of Architectural Degradation during the Maintenance Phase_ research system.

> **Status:** in progress. Architecture recovery currently performs repository ingestion, repository inventory and manifest analysis; database connectivity is wired up. Architecture extraction/validation/detection/scoring logic is not implemented yet.

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
    │   │   └── manifest_analysis/                # Parse manifests into manifest_analysis.json
    │   ├── architecture_validation/
    │   ├── architecture_degradation_detection/
    │   └── degradation_scoring/
    ├── domain/                                   # Domain models and shared research concepts
    ├── infrastructure/                           # Technical adapters (DB, git, external tools)
    └── shared/                                   # Shared utilities and helpers
```

The remaining research components are intentionally empty. Their internal subcomponents will be created in a later task.

## Endpoints

| Method | Path | Purpose |
| ------ | ---- | ------- |
| `GET` | `/` | API root: returns the service message and environment. |
| `GET` | `/health/postgres` | Checks PostgreSQL connectivity. |
| `GET` | `/health/neo4j` | Checks Neo4j connectivity. |
| `POST` | `/repositories` | Clones `{url, branch}`, then inventories and analyzes the clone. |
| `GET` | `/repositories` | Lists ingested repositories. |
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

It runs **automatically after a successful clone**: `POST /repositories` returns
the clone together with an `inventory` summary, or `inventory_error` when the
inventory could not be produced. A failed inventory never fails or rolls back
the clone, because cloning is the primary operation.

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
`POST /repositories` response.

| Format | Analyzer | Extracted |
| ------ | -------- | --------- |
| Docker Compose | `compose` | services, images, build context, published/exposed ports, networks, volumes, environment, `depends_on`, secrets (names only) |
| Kubernetes | `kubernetes` | workloads, containers, images, ports, Service selectors, ConfigMap/Secret references (names only), volume claims |
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

See the root [`ARCHITECTURE.md`](../ARCHITECTURE.md) for the intended future architecture.
