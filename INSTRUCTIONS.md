# INSTRUCTIONS — Development Workflow & Conventions

Conventions for everyone contributing to **architecture-degradation-detector (EAD)** — _Detection of Architectural Degradation during the Maintenance Phase_.

Read this before you write code or open a pull request. These rules are not optional; they are how we keep history clean and the repo recoverable.

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the system design and [`backend/README.md`](./backend/README.md) for the backend layout.

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

| Part | Rule |
| ---- | ---- |
| `type` | **Required.** One of the types in the table below. |
| `scope` | Optional. The area touched, e.g. `api`, `core`, `recovery`, `infra`. |
| `subject` | Required. Imperative mood ("add", not "added"/"adds"), no trailing period, ≤ 72 characters, lowercase after the colon. |
| `body` | Optional. Wrapped at 72 chars. Explain **what** and **why**, not how. Blank line after the subject. |
| `footer` | Optional. Issue references (`Refs: #12`, `Closes: #12`) and the co-author trailer for AI-assisted commits. |

### 2.2 Commit types

| Type | Use for |
| ---- | ------- |
| `feat` | A new feature or capability. |
| `fix` | A bug fix. |
| `docs` | Documentation only. |
| `chore` | Maintenance, tooling, dependency bumps, config. |
| `refactor` | Behavior-preserving restructuring. |
| `test` | Adding or fixing tests only. |
| `perf` | Performance improvement. |
| `build` | Build system or packaging changes. |
| `ci` | CI/CD pipeline changes. |
| `style` | Formatting/lint-only changes. |

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

One logical change per commit. Do not mix refactoring with feature work in the same commit. Never commit secrets — use `.env` (see `backend/.env.example`) and keep `.env` out of git.

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

| Store | Role | Why |
| ----- | ---- | --- |
| **Neo4j** (graph) | Stores recovered/validated **architecture models as graphs** — components, interfaces, dependencies, and their evolution across releases. | Architectural structure is inherently a graph; traversals (paths, cycles, layering violations) are first-class. |
| **PostgreSQL** (relational) | Stores **research metadata** — projects, releases, analysis runs, degradation findings, and scores. | Structured, relational, transactional records with strong querying and reporting. |

Adapters live under [`backend/app/infrastructure/`](./backend/app/infrastructure) (`neo4j/` and `postgres/`). Both services are defined in [`backend/docker-compose.yml`](./backend/docker-compose.yml). Never hardcode credentials or connection strings — configure them through the environment (`backend/.env.example`).

---

## 7. Quick reference

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
