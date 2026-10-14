# INSTRUCTIONS — Development Workflow & Conventions

Conventions for everyone contributing to **architecture-degradation-detector (EAD)** — _Detection of Architectural Degradation during the Maintenance Phase_.

Read this before you write code or open a pull request. These rules are not optional; they are how we keep history clean and the repo recoverable.

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the system design, [`backend/README.md`](./backend/README.md) for the backend layout, and [Section 7](#7-backend-code-layout--file-placement) for the file-placement contract.

---

## 1. Branching model

### 1.1 `develop` is the default branch

- **`develop` is the single source of truth and the default branch.**
- Every change lands on `develop` through a pull request. Nothing is pushed directly to `develop`.
- **Always stay synced with `develop`.** Start every work session by syncing, and rebase your branch on `develop` before you open or update a PR.

```bash
git checkout develop
git pull --ff-only origin develop
```

### 1.2 There is no `main`, no `master`, and no backup branches

- Do **not** create or push a `main` branch, a `master` branch, or any long-lived "backup"/`backup-*` branch.
- Do **not** keep dead branches around "just in case". If you need to recover old work, use its **commit SHA** (see [Section 4](#4-recovering-work-without-backup-branches)).
- Feature branches are **short-lived**: branch off `develop`, merge back via PR, and delete the branch immediately after merge.

### 1.3 Branching off `develop`

```bash
git checkout develop
git pull --ff-only origin develop
git checkout -b <type>/<short-kebab-description>
```

---

## 2. Commit structure

We use **Conventional Commits**. Every commit message must follow this structure:

```
<type>(<optional scope>): <subject>

<optional body>

<optional footer(s)>
```

### 2.1 Rules

| Part      | Rule                                                                                                                   |
| --------- | ---------------------------------------------------------------------------------------------------------------------- |
| `type`    | **Required.** One of the types in the table below.                                                                     |
| `scope`   | Optional. The area touched, e.g. `api`, `core`, `recovery`, `infra`.                                                   |
| `subject` | Required. Imperative mood ("add", not "added"/"adds"), no trailing period, ≤ 72 characters, lowercase after the colon. |
| `body`    | Optional. Wrapped at 72 chars. Explain **what** and **why**, not how. Blank line after the subject.                    |
| `footer`  | Optional. Issue references (`Refs: #12`, `Closes: #12`) and the co-author trailer for AI-assisted commits.             |

### 2.2 Commit types

| Type       | Use for                                         |
| ---------- | ----------------------------------------------- |
| `feat`     | A new feature or capability.                    |
| `fix`      | A bug fix.                                      |
| `docs`     | Documentation only.                             |
| `chore`    | Maintenance, tooling, dependency bumps, config. |
| `refactor` | Behavior-preserving restructuring.              |
| `test`     | Adding or fixing tests only.                    |
| `perf`     | Performance improvement.                        |
| `build`    | Build system or packaging changes.              |
| `ci`       | CI/CD pipeline changes.                         |
| `style`    | Formatting/lint-only changes.                   |

### 2.3 Examples

```
feat(recovery): add static extraction of module dependencies
```

```
fix(api): return 503 when neo4j driver is unavailable

The health endpoint reported 200 even when the graph store was down,
hiding outages from the readiness probe.

Closes: #24
```

```
docs: document develop-first branching workflow
```

One logical change per commit. Do not mix refactoring with feature work in the same commit. Never commit secrets — secrets and environment-specific values go in `.env` (see `backend/.env.example`), which is git-ignored. Non-sensitive tuning values go in the committed `backend/config.ini` instead.

---

## 3. Pull request pattern

### 3.1 Branch naming

`<type>/<short-kebab-description>` — the `type` matches the primary commit type.

```
feat/architecture-recovery-static-extraction
fix/health-endpoint-graph-store
docs/development-instructions
```

### 3.2 Opening a PR

1. Rebase on the latest `develop` first:
   ```bash
   git fetch origin
   git rebase origin/develop
   ```
2. Open the PR **against `develop`** — never against anything else, and never create another long-lived base branch.
3. Title uses the **Conventional Commit format**, e.g. `feat(recovery): add static extraction of module dependencies`.
4. Description explains the change, how it was tested, and links the related issue (`Closes: #<n>`).

### 3.3 Review and merge

- At least one review approval before merge.
- CI must be green.
- **Squash-merge** into `develop` so the merged commit carries a Conventional Commit message and history stays linear:
  ```bash
  git checkout develop
  git pull --ff-only origin develop
  ```
- **Delete the feature branch** immediately after merge — locally and on the remote.

```bash
git branch -d <type>/<short-kebab-description>
git push origin --delete <type>/<short-kebab-description>
```

---

## 4. Recovering work without backup branches

We do **not** keep backup branches. The commit history is the backup. Every commit is addressed by its **SHA**.

Find the commit you need:

```bash
git log --oneline
git log --oneline --all --graph      # include refs you may have deleted locally
```

Inspect or restore it:

```bash
git show <sha>                       # view the change
git checkout <sha>                   # detached HEAD — inspect/run the old state
git switch --detach <sha>            # equivalent on newer git
```

Bring the work back safely (do **not** commit on a detached HEAD):

```bash
git checkout -b recover/<short-description> <sha>
```

Because of this, a **proper commit structure matters** ([Section 2](#2-commit-structure)): a good message and one logical change per commit is what makes SHA-based recovery practical.

---

## 5. Reference system (open source)

The open-source system we use as the research/validation target is **Online Boutique** by Google:

- **Repository:** <https://github.com/GoogleCloudPlatform/microservices-demo>

Online Boutique is Google's cloud-first microservices demo — a web e-commerce app composed of ~10 independent microservices (frontend, cart, checkout, product catalog, recommendation, ads, currency, shipping, email, payment) communicating over gRPC and HTTP. We use it as the subject system for architecture recovery, validation, degradation detection, and scoring.

Treat it as external reference material: do **not** vendor its code into this repository, and respect its license.

---

## 6. Data stores

The system uses **two databases**, each for what it is best at:

| Store                       | Role                                                                                                                                      | Why                                                                                                             |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| **Neo4j** (graph)           | Stores recovered/validated **architecture models as graphs** — components, interfaces, dependencies, and their evolution across releases. | Architectural structure is inherently a graph; traversals (paths, cycles, layering violations) are first-class. |
| **PostgreSQL** (relational) | Stores **research metadata** — projects, releases, analysis runs, degradation findings, and scores.                                       | Structured, relational, transactional records with strong querying and reporting.                               |

Adapters live under [`backend/app/infrastructure/`](./backend/app/infrastructure) (`neo4j/` and `postgres/`). Both services are defined in [`backend/docker-compose.yml`](./backend/docker-compose.yml). Never hardcode credentials or connection strings — secrets and environment-specific values belong in `.env` (`backend/.env.example`); non-sensitive tuning belongs in the committed `backend/config.ini`.

---

## 7. Backend code layout & file placement

This section is the **placement contract**. Before creating any file, find its row below. It is written to be unambiguous for humans _and_ for AI coding agents: if a file does not fit a path listed here, it does not belong in the repository — raise it in the PR instead.

### 7.1 Layers and import direction

```
app/api/              routes + controllers (HTTP)
      │
      ▼
app/components/       research logic  ──►  ports.py Protocols
      ▲                                        ▲
      │                                        │ implement
app/infrastructure/   databases, AI, external tools
```

| Layer          | Path                  | Purpose                                                           | May import                                                                                                              |
| -------------- | --------------------- | ----------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| API            | `app/api/`            | Routes + controllers, request/response schemas, dependency wiring | `components/`, `domain/`, `core/`, `shared/`, and `infrastructure/` **only** to construct adapters in `dependencies.py` |
| Components     | `app/components/`     | Research logic                                                    | its own subcomponents, `domain/`, `core/`, `shared/`                                                                    |
| Domain         | `app/domain/`         | Cross-component research artifacts                                | `shared/`                                                                                                               |
| Infrastructure | `app/infrastructure/` | Database, AI and external-tool adapters                           | `domain/`, `core/`, `shared/`                                                                                           |
| Core           | `app/core/`           | Settings, logging, cross-cutting app configuration                | `shared/`                                                                                                               |
| Shared         | `app/shared/`         | Small generic helpers                                             | Python standard library only                                                                                            |

**Forbidden dependencies** — a PR that introduces one must be rejected:

- `components/` → `infrastructure/`. Depend on a Protocol in `ports.py` instead.
- `components/` → `api/`.
- `infrastructure/` → `api/` or `components/`.
- `domain/` → anything except `shared/`.
- `shared/` → any other layer.
- Importing a vendor LLM SDK anywhere outside `app/infrastructure/ai/providers/`.
- Importing `sqlalchemy` or `neo4j` inside `app/components/`.

### 7.2 Where does this file go?

| I am adding…                                   | Path                                                        | Example                                        |
| ---------------------------------------------- | ----------------------------------------------------------- | ---------------------------------------------- |
| An HTTP endpoint (route + controller)          | `app/api/<feature>.py`                                      | `app/api/architecture_recovery.py`             |
| The aggregating router                         | `app/api/router.py`                                         | `api_router`                                   |
| Request/response models (HTTP contract)        | `app/api/schemas/<feature>.py`                              | `RecoveryRequest`                              |
| `Depends` providers and wiring                 | `app/api/dependencies.py`                                   | `get_recovery_service()`                       |
| A research step (subcomponent)                 | `app/components/<component>/<subcomponent>/`                | `.../architecture_recovery/static_extraction/` |
| Component orchestration                        | `app/components/<component>/service.py`                     | `ArchitectureRecoveryService`                  |
| A model used by one subcomponent               | that subcomponent's `models.py`                             | `SourceFile`                                   |
| A model shared by two or more components       | `app/domain/<name>.py`                                      | `RecoveredArchitecture`                        |
| An interface the component needs from outside  | `app/components/<component>/ports.py`                       | `ArchitectureGraphRepository`                  |
| A database query / CRUD implementation         | `app/infrastructure/<db>/repositories/<name>_repository.py` | `Neo4jArchitectureGraphRepository`             |
| SQLAlchemy table definitions                   | `app/infrastructure/postgres/models/<name>.py`              | `AnalysisRun`                                  |
| A database connection or session factory       | `app/infrastructure/<db>/database.py`                       | `get_db`, `get_neo4j_session`                  |
| An LLM provider adapter                        | `app/infrastructure/ai/providers/<vendor>.py`               | `openai_provider.py`                           |
| Which model handles which task                 | `app/infrastructure/ai/model_configuration.py`              |                                                |
| Prompt templates                               | `app/components/<c>/<subcomponent>/prompts.py`              |                                                |
| A database migration                           | `backend/alembic/versions/`                                 | `0001_create_runs.py`                          |
| Settings and environment config                | `app/core/config.py`                                        | `settings`                                     |
| A tiny generic helper with no domain knowledge | `app/shared/`                                               |                                                |
| A dev or ops script                            | `backend/scripts/`                                          |                                                |

If your file matches no row, stop and discuss it in the PR. **Do not invent a new top-level folder.**

### 7.3 Component & subcomponent pattern (mandatory)

One folder = one subcomponent, and every folder has exactly this shape:

```
<folder>/
├── __init__.py      # re-exports the public class only — no logic
├── service.py       # one class, one public entry method
└── models.py        # data structures local to this folder
```

Rules:

1. **Maximum depth is `components/<component>/<subcomponent>/`.** Never nest a subcomponent inside a subcomponent.
2. A subcomponent may add **private modules** when it outgrows three files (`parsers/`, `heuristics.py`, `prompts.py`) — but never another subcomponent folder.
3. `service.py` must not import FastAPI, SQLAlchemy, Neo4j, or any LLM SDK.
4. The component's `service.py` orchestrates its subcomponents and is the **only** way in. Subcomponents never import each other; if subcomponent A needs B's output, the component passes it in.
5. `api/` imports only `components/<component>/service.py`, never a subcomponent directly.
6. Every directory gets an `__init__.py`. An empty folder is not committed — use `.gitkeep` only for folders that must exist before they have code.

Standard shape of a component:

```
app/components/architecture_recovery/
├── __init__.py
├── service.py                     # ArchitectureRecoveryService — orchestration
├── models.py                      # artifacts and evidence types for this component
├── ports.py                       # Protocols for the outside world
├── static_extraction/
│   ├── __init__.py
│   ├── service.py                 # StaticExtractionService
│   └── models.py
├── deployment_analysis/
├── interface_analysis/
├── runtime_extraction/
├── evidence_correlation/
└── reconstruction/
```

The request path end to end:

```
GET /architecture-recovery/runs/{id}
  app/api/architecture_recovery.py                       route + controller
    app/api/dependencies.py                              wiring (Depends)
      app/components/<component>/service.py              orchestration
        app/components/<c>/<subcomponent>/service.py     research logic
          app/components/<c>/ports.py                    Protocol
            app/infrastructure/<db>/repositories/…       implementation
              app/infrastructure/<db>/database.py        connection
```

### 7.4 Naming

| Thing                     | Convention                                        | Example                            |
| ------------------------- | ------------------------------------------------- | ---------------------------------- |
| Module / file             | `snake_case.py`                                   | `architecture_graph_repository.py` |
| Subcomponent folder       | `snake_case`                                      | `evidence_correlation/`            |
| Class                     | `PascalCase` + role suffix                        | `StaticExtractionService`          |
| Repository implementation | `<Tech><Thing>Repository`                         | `Neo4jArchitectureGraphRepository` |
| Protocol / port           | `PascalCase`, no `I` prefix, no `Protocol` suffix | `ArchitectureGraphRepository`      |
| API schema                | `PascalCase` + `Request`/`Response`               | `RecoveryRequest`                  |
| Test module               | `test_<module>.py`                                | `test_static_extraction.py`        |

### 7.5 Tests mirror the source tree

`app/x/y.py` maps to `tests/x/test_y.py`, packaged with `__init__.py` at every level:

```
app/components/architecture_recovery/static_extraction/service.py
tests/components/architecture_recovery/static_extraction/test_service.py
```

Every new `service.py` ships with its matching test module in the same PR.

### 7.6 Checklist before you create a file

1. Which layer does this belong to? → [§7.1](#71-layers-and-import-direction)
2. Is that import allowed? → the forbidden list in §7.1
3. Can it live in an existing file instead of a new one?
4. Does a `ports.py` Protocol already exist for what I need?
5. Have I added the `__init__.py`?
6. Does it need a test module? → [§7.5](#75-tests-mirror-the-source-tree)
7. Am I inventing a new top-level folder? **Stop** — that is an architecture change, not a code change.

---

## 8. Quick reference

```bash
# Start of session — always sync with develop
git checkout develop && git pull --ff-only origin develop

# New work
git checkout -b feat/<short-description>

# Commit (Conventional Commits)
git commit -m "feat(scope): imperative subject"

# Stay current before opening a PR
git fetch origin && git rebase origin/develop

# After squash-merge into develop — clean up
git checkout develop && git pull --ff-only origin develop
git branch -d feat/<short-description>
git push origin --delete feat/<short-description>

# Recovery — no backup branches, use the SHA
git checkout -b recover/<short-description> <sha>
```
