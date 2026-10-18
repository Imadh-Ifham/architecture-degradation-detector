# C4-ADR-009 — Hotspot rules: fix-message words, events as one unit, release dates from tags

- **Status:** Accepted
- **Date:** 2026-10-18
- **Task:** C4-T13 Hotspot features
- **Decided by:** owner (Dahami)

## Context

§5.2 defines the four hotspot features per *element*, takes release dates for granted and
gives a fix-message pattern. Implementing it raised four questions the plan does not answer,
and showed one gap in the pattern.

## Decision

1. **Fix-message pattern.** §5.2's words `fix|bug|defect|fault|patch|hotfix` miss the most
   common forms: "Fixed login crash", "fixes the totals", "Fixing flaky test" and
   "bugfix: rounding" (`\bbug\b` does not match inside "bugfix"). The keyword list is now
   `fix|fixed|fixes|fixing|bug|bugfix|defect|fault|patch|hotfix` (case-insensitive, whole
   words), and **only fix words count**. §5.2's issue-key alternatives (`#\d+` and
   `[A-Z][A-Z0-9]+-\d+`) were removed after T14 (owner, 2026-10-18): on Online Boutique every
   GitHub squash-merge message ends with `(#PR)`, which made `bugfix_ratio` 1.0 for every
   changed service, and Apache-style Java repositories put a key such as `HADOOP-123` on
   nearly every commit. A message with a key *and* a fix word ("HADOOP-123. Fix NPE",
   "Fixes #12") still counts through the word. The pattern remains a heuristic and a
   declared threat to validity ("resolve crash" is missed, "fix typo" counts).
2. **An event's elements are one unit.** Churn counts each changed file once, even when two
   members own it; authors and commits are counted over all members without duplicates;
   coupling counts elements *outside* the unit that co-change with it in ≥ θ commits (bulk
   commits excluded). Summing per-element values would count shared files twice and inflate
   multi-element events such as cycles.
3. **Release id = git tag.** A release id must name a tag; if it does not, the id with the
   leading `v` added or removed is tried (logged, `tag_v_prefix`), because C3's ids come from
   the release packages, not from git (Online Boutique tags look like `v0.10.0`). Otherwise
   the run stops with `HistoryError` naming both spellings.
4. **Release dates and the half-life.** A release's date is the commit date of its tag. The
   median gap uses C3's release sequence (every release in the events' `series`, plus the
   detected release), not every tag in the repository (release candidates are ignored).
   Fewer than two dated releases, or all on one date, stops the run. Commits dated after the
   detected release (possible after a rebase) count with Δt = 0 and are logged
   (`commit_after_release`).
5. **Authors through `.mailmap`.** The git adapter applies `git check-mailmap`, so one person's
   several addresses count once; C4 lower-cases. Cached rows from before this change are not
   reused (mining rules version 2).

## Alternatives considered

- **Keep §5.2's word list.** Rejected: it would label "Fixed login crash" as not a fix.
- **Keep issue keys, or only closing phrases ("closes #12").** Rejected: keys mark tracked
  work of any kind, not fixes, and closing phrases with a fix word already count.
- **Sum per-element values for multi-element events.** Rejected (decision 2).
- **Skip hotspot when a tag is missing.** Rejected: it would hide a configuration problem.
- **All repository tags for the median gap.** Rejected: pre-release tags would shrink it.

## Consequences

- Tested in `features/test_hotspot.py` (hand-computed churn, unit vs shared file, coupling
  and bulk exclusion, fix messages incl. the misses, `v` prefix, missing tag, half-life,
  future commit) and `tests/infrastructure/git/test_history.py` (`.mailmap`, tag dates).
- The hotspot context (half-life, λ, θ, bulk limit, unmapped line share) goes into the
  manifest and report (T20).
