# C4-ADR-001 — Postgres-backed caches behind ports

- **Status:** Accepted
- **Date:** 2026-10-18
- **Task:** C4-T12 History source + mining cache
- **Decided by:** owner (Dahami)

## Context

Hotspot features (§5.2) need every commit between two release tags. Mining a real
repository with PyDriller takes minutes, and the same range is mined again on every run, so
the result must be cached (NFR-03: re-mining a cached range ≤ 10 % of the first run). The
plan stored the cache as Parquet files, and an early draft used SQLite. The team repo uses
exactly two databases, PostgreSQL and Neo4j (INSTRUCTIONS §6, ARCHITECTURE §6), and
`components/` may not import a database library (INSTRUCTIONS §7.1).

## Decision

1. C4 reaches git history and the cache only through two ports in `<C4>/ports.py`:
   `CommitHistorySource` (PyDriller adapter, `infrastructure/git/history.py`) and
   `MiningCache` (`infrastructure/postgres/repositories/mining_cache_repository.py`). Both
   exchange **plain rows** (dicts), because `infrastructure/` may not import `components/`;
   C4 validates them (`features/history.py`).
2. The cache is one PostgreSQL table, `c4_mining_cache`, keyed by
   `(repo_path, from_tag, to_tag, filter_hash)`, with the filtered commit rows as JSONB.
   Created by migration `0002_c4_mining_cache` (after C3's `0001_c3_ingestion`).
3. `filter_hash` is a sha256 over the include/exclude globs and a rules version
   (`MINING_RULES_VERSION`: range `(from, to]`, merges excluded). Changing the globs or the
   mining rules gives a new key, so stale rows are never reused.
4. Mining rules (owner, 2026-10-18): commits in `(from_tag, to_tag]` (git's `from..to`), merge
   commits left out (they repeat changes already counted), files kept by the configured
   globs, commits with no kept file dropped. Unit tests use an in-memory fake cache.

## Alternatives considered

- **Parquet files** (the plan). Rejected: a second storage mechanism next to the team's
  database, outside its backups and migrations.
- **SQLite** (early draft). Rejected for the same reason; the repo has no SQLite.
- **No cache.** Rejected: NFR-03 and the live demo need the second run to be fast.

## Consequences

- The cache needs PostgreSQL (Docker). Without it, a run can still use the in-memory cache
  (every run mines again).
- The migration is in the shared Alembic history: the team must be told the number (`0002`)
  before the PR, so nobody else creates a second `0002`.
- Tested: `tests/infrastructure/postgres/test_mining_cache_repository.py` (round trip, miss,
  replace, every key part matters) and `features/test_history.py` (second run does not call the
  history source).
