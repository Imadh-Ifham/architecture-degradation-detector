# Backend

Backend for the _Detection of Architectural Degradation during the Maintenance Phase_ research system.

> **Status:** in progress. Repository ingestion and repository inventory exist; database connectivity is wired up. Architecture extraction/validation/detection/scoring logic is not implemented yet.

## Structure

```
backend/
└── app/
    ├── api/                                      # HTTP/REST layer (FastAPI)
    ├── core/                                     # Cross-cutting application concerns
    ├── components/                               # Research components
    │   ├── architecture_recovery/
    │   │   ├── repository_ingestion/             # Clone/remove a repository in a local workspace
    │   │   └── repository_inventory/             # Inventory a working tree into repository_inventory.json
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
| `POST` | `/repositories` | Clones `{url, branch}` into the ingestion workspace and inventories the clone. |
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

Limits and extra exclusions are configurable through the `INVENTORY_*` settings
(see `backend/.env.example`).

See the root [`ARCHITECTURE.md`](../ARCHITECTURE.md) for the intended future architecture.
