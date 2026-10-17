# Architecture

**Research system:** Detection of Architectural Degradation during the Maintenance Phase

This document describes the **intended future architecture**. It documents boundaries, responsibilities, data flows, and planned structures. It does **not** describe what is implemented today.

> **Current state:** the backend skeleton exists — settings, a FastAPI app with health endpoints, and both database adapters. The four component folders are intentionally still empty. Everything described below about **component internals** (subcomponents and their files) is **planned** and will be created as the research work is implemented.

---

## 1. System Overview

The system detects architectural degradation in software systems during their maintenance phase. It does so by recovering the architecture as it actually exists, validating it against the architecture as it was intended, detecting degradation across releases, and scoring the severity of what was found.

### Research pipeline

```
Architecture Recovery  →  Architecture Validation  →  Architecture Degradation Detection  →  Degradation Scoring
   (as-is model)            (intent vs. reality)            (across releases)                     (severity)
```

Each stage consumes artifacts produced by the previous stage, together with its own external evidence.

| Component                          | Consumes                                                                    | Produces                               |
| ---------------------------------- | --------------------------------------------------------------------------- | -------------------------------------- |
| Architecture Recovery              | Source repository, deployment/runtime evidence                              | **Recovered Architecture Model/Graph** |
| Architecture Validation            | Recovered architecture, external architectural-intent evidence (ADRs, docs) | **Validated Architecture**             |
| Architecture Degradation Detection | Validated architecture, release/change evidence                             | **Degradation Findings**               |
| Degradation Scoring                | Degradation findings                                                        | **Scored Degradation Findings**        |

---

## 2. Repository Layout (current)

The physical skeleton established now:

```
/
├── frontend/
├── backend/
│   └── app/
│       ├── api/
│       ├── core/
│       ├── components/
│       │   ├── architecture_recovery/
│       │   ├── architecture_validation/
│       │   ├── degradation_detection/
│       │   └── degradation_scoring/
│       ├── domain/
│       ├── infrastructure/
│       └── shared/
└── ARCHITECTURE.md
```

### Backend top-level responsibilities

| Folder                | Responsibility                                                                                |
| --------------------- | --------------------------------------------------------------------------------------------- |
| `app/api/`            | HTTP/REST layer. Exposes research functionality to the frontend.                              |
| `app/core/`           | Application-level cross-cutting concerns shared by all components.                            |
| `app/components/`     | The four research components. Each is a self-contained unit of research logic.                |
| `app/domain/`         | Domain models: the core research concepts and artifacts, independent of storage or transport. |
| `app/infrastructure/` | Technical adapters to the outside world: databases, AI/LLM access, external tooling.          |
| `app/shared/`         | Small, dependency-free helpers reused across layers.                                          |

---

## 3. Research Components

### 3.1 Architecture Recovery

**Purpose:** Reconstruct the architecture of a system **as it actually is** — the ground truth used by every later stage.

**Planned subcomponents:**

- **Repository ingestion** — clone a target repository at a given branch into a local workspace, and remove it again.
- **Repository inventory** — inventory the working tree into a versioned JSON document (files, classifications, candidate components, relationships) that later stages consume.
- **Manifest analysis** — parse the manifests the inventory found (Compose, Kubernetes, Dockerfile, OpenAPI, Protobuf) into declared resources, endpoints and relationships, keeping declared dependencies, configured endpoints and API definitions distinct.
- **Component discovery** — identify the logical components (services, applications, modules) and associate the artifacts that implement, define, build, deploy and contract each one, keeping artifacts distinct from components and recording evidence, uncertainty and unresolved cases.
- **Static extraction** — derive structural information from source code and build artifacts.
- **Deployment analysis** — derive deployment topology and environment structure from deployment descriptors and configuration.
- **Interface analysis** — identify interfaces, contracts, and communication boundaries between parts of the system.
- **Runtime extraction** — derive behavior and actual interaction information from runtime evidence.
- **Evidence normalization/correlation** — normalize heterogeneous evidence into a common representation and correlate facts that describe the same architectural element.
- **Architecture reconstruction** — assemble the normalized, correlated evidence into a coherent architectural model.

**Produces:** the **Recovered Architecture Model/Graph** — the as-is architecture, typically represented as a graph of elements and relationships.

**External evidence:** consumes a source repository, plus deployment and runtime evidence.

---

### 3.2 Architecture Validation

**Purpose:** Determine whether the recovered architecture matches the architecture that was **intended**.

**Subcomponents — the first four are built; the four after them are planned:**

- **Observation normalization** — turn the recovered architecture into one uniform fact per relationship, whatever architectural style it came from, with every element name reduced to a single identity and every release identifier made orderable.
- **Decision knowledge** — hold the architectural decisions as an append-only history and answer which one governed a relationship at a given release, with three sources behind one protocol (records in the code repository, records in a repository the user names, rules reconstructed from the repository's own configuration) and half-open validity intervals so a superseded decision never governs.
- **Evidence retrieval** — assemble the fixed, ordered, hashed set of text a verdict may be reasoned from, each item quoted from the lines it was read from and carrying a reference a citation can be checked against.
- **Validation reasoning** — judge one fact against the decision that governs it, under an enforced response schema and a versioned prompt, with every citation checked against the evidence it was given.
- **Independent verification** — re-examine a verdict as a challenge to it, using a different model and a different framing; it may lower a conclusion and never raise one.
- **Classification** — turn a verdict and its verification into a bucket, a confidence with its arithmetic published, and a route, with the strength of the evidence capping the strength of the conclusion.
- **Architect review** — hold back what the system will not decide alone, and record what a person decided.
- **Graph publishing** — publish the validated architecture as a graph with each verdict carried on the relationship it describes.

**Consumes:** the Recovered Architecture Model/Graph, plus external architectural-intent evidence. Where recovery's own output for a release is not yet available, a recorded recovery output is read instead, through the same port and stamped on the run's provenance.

**Produces:** the **Validated Architecture** — the recovered architecture annotated with validation results and violations.

**Boundary:** validation reads no source code. It reads recovery's description of the architecture, and the configuration and decision documents recovery has already located, through a port whose implementation lives outside the component.

---

### 3.3 Architecture Degradation Detection

**Purpose:** Identify where and how architecture has degraded over the system's lifetime, and why.

**Planned areas:**

- **Release/change analysis** — analyze what changed between releases or over a change history.
- **Architecture comparison across releases** — compare architectural models across time.
- **Degradation detection** — identify architectural degradation between those states.
- **Cause analysis** — attribute detected degradation to its likely causes.

**Consumes:** the Validated Architecture, plus release/change evidence.

**Produces:** **Degradation Findings** — located, described instances of architectural degradation.

---

### 3.4 Degradation Scoring

**Purpose:** Quantify the severity and impact of detected degradation so findings can be prioritized.

**Planned areas:**

- **Scoring engine** — apply scoring logic consistently across findings.
- **Severity calculation** — compute severity from finding characteristics.
- **Scoring rules** — externalized, maintainable rules that drive scoring and severity.

**Consumes:** Degradation Findings.

**Produces:** **Scored Degradation Findings** — findings annotated with scores and severity.

---

## 4. Component Internal Structure

**Status: planned.** The four component folders exist and are intentionally empty. The structure below is the standard that every component and every subcomponent must follow, so that later work lands in the intended places and respects the established boundaries.

### 4.1 The standard folder shape

One folder = one subcomponent, and every folder has the same three files:

```
<folder>/
├── __init__.py      # re-exports the public class only
├── service.py       # one class, one public entry method — no framework imports
└── models.py        # data structures local to this folder
```

Applied to a component:

```
components/<component>/
├── __init__.py
├── service.py                  # orchestrates the subcomponents
├── models.py                   # artifacts and evidence types used by this component
├── ports.py                    # Protocols for anything outside: repositories, AI, extractors
└── <subcomponent>/
    ├── __init__.py
    ├── service.py
    └── models.py
```

Rules:

- Maximum depth is `components/<component>/<subcomponent>/`. Never nest a subcomponent inside a subcomponent.
- Subcomponents never import each other. The component's `service.py` orchestrates them and passes artifacts between them.
- `service.py` never imports FastAPI, SQLAlchemy, Neo4j, or any LLM SDK.
- Dependencies on the outside world are declared as Protocols in `ports.py` and implemented under `app/infrastructure/`.
- A subcomponent may add private modules (`parsers/`, `heuristics.py`, `prompts.py`) when it outgrows three files — but never another subcomponent folder.

### 4.2 Planned subcomponents per component

| Component                 | Subcomponents                                                                                                                    |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `architecture_recovery`   | `static_extraction`, `deployment_analysis`, `interface_analysis`, `runtime_extraction`, `evidence_correlation`, `reconstruction` |
| `architecture_validation` | `validation_reasoning`, `independent_verification`, `classification`, `architect_review`, `graph_publishing` |
| `degradation_detection`   | `release_analysis`, `architecture_comparison`, `detection`, `cause_analysis`                                                     |
| `degradation_scoring`     | `scoring_engine`, `severity`, `rules`                                                                                            |

`architecture_validation`'s pipeline is **eight** subcomponents, and the first **four** are built
(normalization, decision knowledge, evidence retrieval and validation reasoning). The four names originally listed are
preserved rather than dropped:

| Originally listed | Where its responsibility now sits |
| ----------------- | --------------------------------- |
| `adr_extraction`        | `decision_knowledge/sources/repo_adr.py` and `external_adr.py` — one source among three, because most repositories hold no decision records |
| `intent_extraction`     | `decision_knowledge/sources/config_scan.py` — reading intent out of configuration produces decision records, so it belongs to the subcomponent that holds them |
| `constraint_extraction` | the closed `ConstraintKind` vocabulary every source normalises into, in the component's own `models.py` |
| `validation`            | split across `validation_reasoning`, `independent_verification`, `classification` and `graph_publishing`, which have different dependencies and different failure modes |

The split follows §4.1: one folder is one subcomponent with one responsibility. `validation` as a
single folder would have held the model calls, the verification, the scoring rules and the output
serialisation — four things that change for four unrelated reasons.

### 4.3 Resulting tree (created incrementally)

```
components/
├── architecture_recovery/
│   ├── static_extraction/
│   ├── deployment_analysis/
│   ├── interface_analysis/
│   ├── runtime_extraction/
│   ├── evidence_correlation/
│   └── reconstruction/
├── architecture_validation/
│   ├── validation_reasoning/
│   ├── independent_verification/
│   ├── classification/
│   ├── architect_review/
│   └── graph_publishing/
├── degradation_detection/
│   ├── ingestion/
│   ├── detection/
│   ├── tracking/
│   ├── trends/
│   ├── reasoning/
│   ├── events/
│   └── review/
└── degradation_scoring/
    ├── scoring_engine/
    ├── severity/
    └── rules/
```

Each folder above also gets `__init__.py`, `service.py` and `models.py` when it is created.

**Where everything else goes** — routers, schemas, repositories, ORM tables, prompts, migrations — is defined in [`INSTRUCTIONS.md` §7](./INSTRUCTIONS.md#7-backend-code-layout--file-placement). Follow it when adding files.

---

## 5. AI / LLM Architecture

Different components — and different subcomponents within a component — have different needs. Some tasks favor large reasoning models, others favor smaller, cheaper, or locally hosted models. The architecture must therefore allow **per-task model selection** rather than a single global model.

### Planned structure

```
app/infrastructure/ai/
├── interface.py               # Provider- and model-agnostic abstraction
├── model_registry.py          # Known models and their capabilities
├── model_configuration.py     # Which model is used for which task
└── providers/                 # Concrete provider adapters
    ├── __init__.py
    └── <vendor>.py
```

A provider adapter is named for the **API contract it speaks**, not always for a single vendor. Several
hosted and local runtimes expose the same OpenAI-compatible chat-completions API, so one
`openai_compatible.py` adapter serves all of them and the provider becomes configuration rather than
code. A vendor-specific adapter is still named for its vendor where the API is genuinely proprietary.


> These folders and files are **not created now**.

### Key rule: always go through the abstraction

Components and subcomponents must **never** depend directly on a specific LLM provider or a specific model. All AI usage goes through the AI interface, which resolves the appropriate model for the task and delegates to the corresponding provider.

```
Component/Subcomponent
        ↓
   AI Interface
        ↓
 Model Selection
        ↓
  Selected LLM
        ↓
    Provider
```

This keeps research logic independent of vendor APIs, allows swapping models without touching component code, and makes it possible to compare model behavior as part of the research.

---

## 6. Databases

The system uses exactly two databases, each chosen for a distinct kind of data:

```
app/infrastructure/
├── postgres/
│   ├── database.py            # engine, SessionLocal, Base, get_db
│   ├── models/                # SQLAlchemy tables              [planned]
│   └── repositories/          # query / CRUD implementations   [planned]
└── neo4j/
    ├── database.py            # driver, get_neo4j_session
    └── repositories/          # Cypher-based graph access      [planned]
```

> The connection layer (`database.py`) exists. `models/` and `repositories/` are **planned** and are added as tables and queries are needed. Repositories implement the Protocols declared in each component's `ports.py` — components never import them directly.

| Database       | Data it holds                                                                                                                                                   | Why                                                                                                                                   |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| **PostgreSQL** | Relational, application, and metadata data: research runs, projects, releases, findings metadata, scoring results, configuration, audit and provenance records. | Well-suited to well-defined, tabular, transactional data with integrity constraints and queryable relationships across records.       |
| **Neo4j**      | Architecture graphs and graph relationships: recovered architecture models, elements, dependencies, and cross-release architectural comparisons.                | Architecture is naturally a graph; graph traversal and path-based analysis are first-class rather than emulated with recursive joins. |

They are kept separate because their access patterns and data shapes are fundamentally different. Forcing graph structures into a relational schema makes traversal expensive and the model awkward; forcing relational metadata into a graph adds no value. Each database is used for what it is good at, and findings in one reference elements identified by stable identifiers in the other.

---

## 7. Communication

### Primary flow

```
Frontend
    ↓ HTTP/REST
FastAPI API
    ↓
Research Components

Architecture Recovery
    ↓
Architecture Validation
    ↓
Architecture Degradation Detection
    ↓
Degradation Scoring
```

The frontend talks only to the FastAPI API. The API drives the research components, which pass artifacts down the pipeline.

### External evidence inputs

Components also receive evidence directly, not only from upstream components:

```
Source Repository ──────────────→ Architecture Recovery

Deployment/Runtime Evidence ────→ Architecture Recovery

ADR Repository ─────────────────→ Architecture Validation

Release/Change Evidence ────────→ Degradation Detection
```

### Boundary rule

The **frontend must never directly access**:

- PostgreSQL
- Neo4j
- Git repositories
- extraction tools
- LLM providers

All access is mediated by the backend API. This keeps the frontend a pure presentation client and keeps research logic, credentials, and infrastructure concerns entirely server-side.

---

## 8. Scope

**Implemented today:**

- `frontend/` (placeholder)
- backend skeleton: `app/api/`, `app/core/`, `app/components/`, `app/domain/`, `app/infrastructure/`, `app/shared/`
- settings and environment configuration (`app/core/config.py`)
- FastAPI application (`app/main.py`) and the health router (`app/api/health.py`) exposing `/health/postgres` and `/health/neo4j`
- database connection layer: `app/infrastructure/postgres/database.py`, `app/infrastructure/neo4j/database.py`
- alembic scaffolding, `docker-compose.yml` (PostgreSQL + Neo4j), pytest setup

**Not implemented yet:**

- any subfolder inside the four research components ([§4](#4-component-internal-structure))
- per-component routers and request/response schemas
- repositories and SQLAlchemy models
- LLM/AI layer ([§5](#5-ai--llm-architecture))
- extraction, correlation and reconstruction logic
- graph logic
- degradation detection logic
- scoring logic
- frontend UI

This document defines _what_ the system is and which boundaries exist. [`INSTRUCTIONS.md` §7](./INSTRUCTIONS.md#7-backend-code-layout--file-placement) defines _where each file goes_ — read it before adding code.
