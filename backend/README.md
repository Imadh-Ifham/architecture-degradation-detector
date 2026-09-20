# Backend

Backend skeleton for the _Detection of Architectural Degradation during the Maintenance Phase_ research system.

> **Status:** structure only. No endpoints, database connections, extraction logic, or AI integrations are implemented yet.

## Structure

```
backend/
└── app/
    ├── api/                                      # HTTP/REST layer (FastAPI) — to be implemented
    ├── core/                                     # Cross-cutting application concerns
    ├── components/                               # Research components
    │   ├── architecture_recovery/
    │   ├── architecture_validation/
    │   ├── architecture_degradation_detection/
    │   └── degradation_scoring/
    ├── domain/                                   # Domain models and shared research concepts
    ├── infrastructure/                           # Technical adapters (DB, AI, external tools)
    └── shared/                                   # Shared utilities and helpers
```

The four research components are intentionally empty. Their internal subcomponents will be created in a later task.

See the root [`ARCHITECTURE.md`](../ARCHITECTURE.md) for the intended future architecture.
