# C4-ADR-012 — ADR-violation weight: links only from C2, max per event, fixed table

- **Status:** Accepted
- **Date:** 2026-10-18
- **Task:** C4-T16 ADR loader + AV weighter
- **Decided by:** owner (Dahami)

## Context

§5.3 computes AV only "for events where C2 provided `adr_refs`". C2 does not produce those
links yet (C4-ADR-007, A5), and C3's `context.cited` is empty while its context stage is
disabled. The release package does carry `intent[]` entries that attach ADRs to elements
(e.g. ADR-0002 → catalog-service). §5.3 also does not say how to combine several linked
ADRs, and its weight table could be read as tunable settings.

## Decision

1. **Links come only from C2.** The `AdrIndexSource` port delivers the ADR documents and C2's
   element → violated-ADR links. C4 never treats `intent[]` (or anything else) as a violation
   link: an ADR *about* catalog-service is not broken by every catalog-service problem, and
   deciding a violation is C2's job (CLAUDE.md §2).
2. **Max per event.** An event's AV is the weight of the most serious ADR linked to any of
   its elements (ties: smallest ADR id). Summing would reward events for being linked to
   many minor rules.
3. **Fixed table.** The status and scope weights are constants in `features/adr_weight.py`
   (they are the definition, like the fix words), recorded per run in `AdrContext` for the
   manifest. Unknown status weighs 0.0 (no sign the decision is in force); a missing scope is
   `unspecified` (0.4).
4. **Off, and why.** No index ⇒ `no_adr_index`; an index without ADRs ⇒ `empty_adr_index`.
   The features subcomponent only reports the state; renormalising the other criteria's
   weights is AHP's job and is tested in T18.

## Alternatives considered

- **Use `intent[]` element links as violation links.** Rejected (decision 1).
- **Sum of linked ADR weights.** Rejected (decision 2).
- **Seven settings for the table.** Rejected: invites tuning a definition.

## Consequences

- In every real PP1 run AV is inactive; the ranking uses BR, EH and PS. Gate 2 (end M4)
  decides AV's fate, e.g. from C2's edge verdicts (C4-ADR-007 A5).
- The mechanism is proven on fixtures: `adr/adr_links.v1.json` (labelled stand-in) gives the
  designed AV 1.0 / 0.14 / 0.2 / 0 (`features/test_adr_weight.py`); parsing is tested in
  `ingestion/test_adr.py`.
- **T21 addendum (owner, 2026-10-19).** The Online Boutique AV-on run uses a labelled fixture
  stand-in, `adr/online_boutique/` (two hand-written ADRs + `adr_links.v1.json`,
  `data_provenance: fixture`), only to show the AV switch on a real repository. It is not C2
  output and not a finding; real runs without C2 links still have AV inactive.
