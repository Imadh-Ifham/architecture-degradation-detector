# C4-ADR-011 — Manual source-path mapping and a full clone for Online Boutique (T14)

- **Status:** Accepted (temporary: until C2's source_paths pass-through, M8)
- **Date:** 2026-10-18
- **Task:** C4-T14 Hotspot on the real demo repo
- **Decided by:** owner (Dahami)

## Context

Hotspot attributes changed files to elements through each graph node's `source_paths`
(§5.2, stand-in A4 in C4-ADR-007). C2's pass-through of those paths is planned for M8 and not
started, so no real graph of Online Boutique (the group's reference system, INSTRUCTIONS §5)
carries paths yet. T14 must still show hotspot mining on the real repository.

The plan also takes the repository from C1's ingestion workspace (`settings.repositories_root`).
C1 clones with `--depth 1 --single-branch` (`infrastructure/git/client.py`): the clone has one
commit and no tags, so it cannot be mined.

## Decision

1. A hand-made mapping file,
   `tests/fixtures/degradation_scoring/mappings/online_boutique.source_paths.v1.json`, maps
   each of the 12 service folders to `src/<service>/**` (checked at `v0.10.7`). It is labelled
   `"data_provenance": "manual-mapping"`, and every output built from it says
   `live-history+manual-mapping` in its manifest. It is replaced by C2's pass-through when M8
   delivers it; nothing in C4's code depends on the file.
2. C4 mines a **full clone with tags** at `<repositories_root>/c4-history/<repo-name>`, next to
   C1's workspace entries (C1 skips folders without its `metadata.json`). C4 only reads its
   history and never runs its code. On the owner's machine `REPOSITORIES_ROOT` is set in
   `backend/.env` to `C:\repos\add-repositories` (owner, 2026-10-18), so Online Boutique lives
   at `C:\repos\add-repositories\c4-history\microservices-demo`. The default (the system temp
   folder) can be wiped by disk cleanup; the cache key includes the clone's path, so a moved
   clone is mined once more and then cached again.
3. The profile is produced by `backend/scripts/c4_hotspot_profile.py` (one invocation = one run,
   PostgreSQL mining cache, outputs and manifest in `<C4>/docs/pp1/figures/`).

## Alternatives considered

- **Wait for C2's pass-through.** Rejected: T14 and the PP1 demo would have no real-repo
  hotspot evidence.
- **Ask C1 for full clones.** Not rejected: a request to C1 (an option for history depth)
  would let C4 reuse C1's workspace; until then C4 keeps its own clone.
- **Per-file mapping.** Rejected: files added after the mapping would be unmapped (T12).

## Consequences

- Online Boutique's mapping is complete by construction (`unmapped_line_share` = 0.0 on the
  profiled windows), so it cannot show how well a real C2 mapping covers the code.
- Findings from the profile that affect later tasks are recorded in the T14 tracker entry.
