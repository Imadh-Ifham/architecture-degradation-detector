# C3: Degradation Detection

C3 receives validated release packages of one system (from C2), detects architectural
anti-patterns in every release, tracks each anti-pattern and each element across releases, and
uses Mann-Kendall, Sen's slope and Benjamini-Hochberg to report **only what is statistically
getting worse**, as `DegradationEventV2` events for C4. C3 does not rank: there is no severity in
its output, and C4 decides what matters most.

```
C1 Architecture Recovery -> C2 Architecture Validation -> C3 Degradation Detection -> C4 Degradation Scoring
```

| Module | Folder | PP1 |
|---|---|---|
| M1 ingestion: validate, normalise, confidence gate, store, timeline | `ingestion/` | yes |
| M2 detection: graph, metrics, anti-pattern detectors (fitness functions) | `detection/` | yes |
| M3 tracking: element lineages, instance tracks, series | `tracking/` | yes |
| M4 trends: Mann-Kendall, Sen's slope, Benjamini-Hochberg, candidates | `trends/` | yes |
| M6 events: export to `DegradationEventV2` (context disabled) | `events/` | export only |
| Run report and static-threshold baseline | `report/`, `baselines/` | yes |
| Synthetic system with planted ground truth | `stub/` | yes |
| M5 contextual reasoning (RAG), M7 architect review and audit trail | | after PP1 |

The component's `service.py` (`DegradationDetectionService`) is the only way in. The design,
contracts and every decision are in [docs/implementation-plan.md](../../../../docs/implementation-plan.md)
and [docs/adr/](../../../../docs/adr/).

## Requirements

- Windows PowerShell 5.1 or later
- [uv](https://docs.astral.sh/uv/) (it installs Python 3.13 itself)
- Docker Desktop, running (PostgreSQL)

## Demo: one command

From the repository root:

```powershell
backend/scripts/demo.ps1
```

On a fresh clone this takes under two minutes once Docker images are pulled. It needs no `.env`.
It runs:

1. `uv sync`, then starts the PostgreSQL container from `backend/docker-compose.yml`;
2. drops and recreates the **`c3_demo`** database and runs the migrations from empty (your
   development database is never touched);
3. generates the synthetic system `shopfront` (10 releases, planted scenarios S1-S11);
4. ingests it: 10 releases stored (one downweighted), one package rejected;
5. analyses it under the run `RUN-demo`;
6. re-renders the report from the stored run;
7. scores the run against the ground truth.

Outputs, in `backend/out/RUN-demo/`:

| File | What it is |
|---|---|
| `events.json` | the `DegradationEventV2` events for C4 |
| `series.csv` | every series (element, instance, system) in long form, nulls kept |
| `report.md` | the run: config hash, versions, anti-patterns per release, tested and untested series, events |
| `plots/<event_id>.png` | each event's series with its Sen's slope line |
| `mvp_eval.md` | the evaluation: every claim, its ground truth and its metric |

The run id is fixed, so running the demo again gives byte-identical events: the same config gives
the same events. Use `-SkipSync` to skip `uv sync` on later runs.

The stub is a development fixture, not evidence: it shows that the pipeline finds what was
planted, nothing more.

## Step by step

The commands below use the database in `backend/.env` (copy `.env.example`; the dev password is
in `docker-compose.yml`). Run them from `backend/` after `docker compose up -d` and
`uv run alembic upgrade head`. Every command has `--help`.

| Step | Command |
|---|---|
| Generate the synthetic system | `uv run python -m scripts.c3 stub generate` |
| Ingest (gate summary) | `uv run python -m scripts.c3 ingest data/samples/shopfront` |
| Anti-patterns per release | `uv run python -m scripts.c3 detect --system shopfront` |
| Lineages, rename, instance tracks | `uv run python -m scripts.c3 align --system shopfront` |
| Series table | `uv run python -m scripts.c3 series --system shopfront` |
| Trends and events (not stored) | `uv run python -m scripts.c3 trends --system shopfront` |
| Full stored run | `uv run python -m scripts.c3 run --system shopfront` |
| Re-render a run's report | `uv run python -m scripts.c3 report --run-id RUN-...` |
| Static-threshold baseline | `uv run python -m scripts.c3 baseline --system shopfront` |
| Evaluate a run | `uv run python -m scripts.mvp_eval --run-id RUN-...` |
| Show the config and its hash | `uv run python -m scripts.c3 config show` |
| Export the contract schemas | `uv run python -m scripts.c3 schemas export` |

`detect`, `align`, `series` and `trends` show one step at a time and store nothing; `run` is the
pipeline.

## Configuration

`backend/configs/default.yaml` (statistics, thresholds, gate) and `backend/configs/catalog.yaml`
(which detector runs for which architecture style). Both are validated (an unknown key fails) and
hashed together into the `config_hash` stored on every run and event.

## Quality gate

```powershell
backend/scripts/check.ps1        # ruff, mypy --strict, C3 tests, coverage (no Docker needed)
backend/scripts/check.ps1 -All   # the whole backend suite, with the PostgreSQL tests
```

Coverage gates: at least 85% on the component and 95% on `trends/`. Mann-Kendall, Sen's slope and
Benjamini-Hochberg are implemented here; `scipy`, `pymannkendall` and `statsmodels` are used only
as test and evaluation oracles.
