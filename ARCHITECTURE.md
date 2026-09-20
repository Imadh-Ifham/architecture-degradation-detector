# Architecture

**Research system:** Detection of Architectural Degradation during the Maintenance Phase

This document describes the **intended future architecture**. It documents boundaries, responsibilities, data flows, and planned structures. It does **not** describe what is implemented today.

> **Current state:** structure-only skeleton. The physical repository contains top-level boundaries (`frontend/`, `backend/app/*`, and the four component folders). All subcomponents described below are **planned** and will be created in later tasks.

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
│       │   ├── architecture_degradation_detection/
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

**Planned areas:**

- **ADR extraction** — extract architectural decisions from Architecture Decision Records.
- **Architecture intent extraction** — derive intended structure and qualities from documentation and other intent sources.
- **Constraint extraction** — derive explicit and implicit architectural constraints.
- **Comparison/validation** — compare the recovered architecture against the extracted intent and constraints.
- **Violation detection** — identify and report where reality diverges from intent.

**Consumes:** the Recovered Architecture Model/Graph, plus external architectural-intent evidence.

**Produces:** the **Validated Architecture** — the recovered architecture annotated with validation results and violations.

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

## 4. Planned Future Component Structure

The following internal structure is **planned** but **not created yet**. It is documented here so that later tasks create subcomponents in the intended places and respect the established boundaries.

```
components/
├── architecture_recovery/
│   ├── static_extraction/
│   ├── deployment_analysis/
│   ├── interface_analysis/
│   ├── runtime_extraction/
│   └── reconstruction/
│
├── architecture_validation/
│   ├── adr_extraction/
│   └── validation/
│
├── architecture_degradation_detection/
│   └── change_analysis/
│
└── degradation_scoring/
    └── scoring/
```

These folders must not be created as part of the initial skeleton. They will be introduced when the corresponding research work begins.

---

## 5. AI / LLM Architecture

Different components — and different subcomponents within a component — have different needs. Some tasks favor large reasoning models, others favor smaller, cheaper, or locally hosted models. The architecture must therefore allow **per-task model selection** rather than a single global model.

### Planned structure

```
infrastructure/
└── ai/
    ├── interface              # Provider- and model-agnostic abstraction
    ├── model_registry         # Known models and their capabilities
    ├── model_configuration    # Which model is used for which task
    └── providers              # Concrete provider adapters
```

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
infrastructure/
└── database/
    ├── postgres/
    └── neo4j/
```

> These folders are **not created now**.

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

## 8. Scope of the Current Skeleton

Created now:

- `frontend/` (placeholder)
- `backend/app/api/`, `backend/app/core/`, `backend/app/domain/`, `backend/app/infrastructure/`, `backend/app/shared/`
- `backend/app/components/` with the four component folders
- `ARCHITECTURE.md`

Deliberately **not** created or implemented:

- any subfolder inside the four components
- FastAPI endpoints
- database connections
- LLM integrations
- extraction logic
- graph logic
- degradation detection logic
- scoring logic
- frontend UI

This document is the reference for how those pieces will be added later.
