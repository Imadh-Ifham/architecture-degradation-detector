# Backend

Backend for the _Detection of Architectural Degradation during the Maintenance Phase_ research system.

> **Status:** in progress. Repository ingestion and health endpoints exist; database connectivity is wired up. Architecture extraction/validation/detection/scoring logic is not implemented yet.

## Structure

```
backend/
└── app/
    ├── api/                                      # HTTP/REST layer (FastAPI)
    ├── core/                                     # Cross-cutting application concerns
    ├── components/                               # Research components
    │   ├── architecture_recovery/
    │   │   └── repository_ingestion/             # Clone/remove a repository in a local workspace
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
| `POST` | `/repositories` | Clones `{url, branch}` into the ingestion workspace. |
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

See the root [`ARCHITECTURE.md`](../ARCHITECTURE.md) for the intended future architecture.
