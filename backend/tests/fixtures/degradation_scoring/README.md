# C4 fixtures (synthetic)

**Everything here is hand-designed test data, not results.** Any report built from it has
`data_provenance: "fixture"` and a fixture banner. The system `c4-fixture-shop` does not
exist. Checked by `tests/components/degradation_scoring/test_fixtures.py`.

| File | Purpose |
|---|---|
| `graphs/fixture_release_package.v1.5.0.json` | The graph C4 loads: a `ReleasePackageV1.1` (C3's input format) for release `v1.5.0`. 22 services; one 4-service cycle (order → payment → inventory → shipping → order); a hub (`common-lib`, 11 dependents); a bridge (`integration-hub`, the only link from the back-office services to the core); `order-service` renamed from `order-svc` (alias); `admin-ui` and `web-frontend` have no `extra.source_paths`; three `intent[]` entries link to the ADRs below. |
| `events/fixture_events.v1.json` | 17 C3 payloads: 14 valid `DegradationEventV2` events and 3 malformed ones (last three). One of each outcome C4 must handle; see the table below. |
| `fixture_expected.json` | The designed outcome of every payload (ranked / skipped / quarantined, resolution, fallback values and C3 V2.1.0 values), plus total counts. Ingestion and feature tests assert against it. |
| `adr/0001…0003-*.md` | Three MADR decision records with front matter: accepted + system, superseded + component, proposed + local, i.e. three different AV weights (§5.3). |
| `adr/adr_links.v1.json` | **Synthetic stand-in for C2's `adr_refs`** (element → violated ADR): ADR-0001 → inventory-service, ADR-0002 → reporting-service, ADR-0003 → notification-service, plus the designed AV of each ranked event (1.0 / 0.14 / 0.2 / 0). Real PP1 runs have no such links, so AV is inactive there (C4-ADR-007 A5, C4-ADR-012). |
| `mappings/online_boutique.source_paths.v1.json` | **Manual mapping** (not a fixture of C2 output): each Online Boutique service folder as `src/<service>/**`, used by `scripts/c4_hotspot_profile.py` (T14) until C2's source_paths pass-through exists (C4-ADR-011). `data_provenance: manual-mapping`. |
| `legacy/prototype.py` | The old C4 feasibility prototype, kept **unchanged** as a regression reference: `features/test_blast_radius_prototype.py` rebuilds its 13-module graph and reproduces its blast-radius numbers for its 6 events. Only its blast radius was computed; its other dimensions are hardcoded stubs. It runs on load (prints, writes two report files), so the test runs it in a temporary folder. Excluded from ruff and mypy in `pyproject.toml`. |

The provisional AHP matrix is not a fixture: it lives with the code at
`app/components/degradation_scoring/scoring_engine/weights/ahp_v1.json`
(`provenance: provisional-author-elicited`).

## Events

| # | Event | Designed outcome | Why it is here |
|---|---|---|---|
| E01 | INSTANCE CyclicDependency, CONFIRMED | ranked, exact | V2.1.0 first-seen (`v1.2.0`) earlier than the window start (`v1.3.0`): null at the series start |
| E02 | ELEMENT HubLikeElement on `common-lib`, CONFIRMED | ranked, exact | V2.1.0 presence (3 releases) vs series fallback (6): the overcount C3 described |
| E03 | ELEMENT OversizedElement, no instance | ranked, exact | no `instance_id`, so the fallback is used even after V2.1.0 |
| E04 | ELEMENT UnstableDependency | ranked, exact | gap in the series (`v1.1.0` null) for consecutive-release counting |
| E05 | ELEMENT MetricDrift on the bridge, UNCERTAIN | ranked, exact | UNCERTAIN is ranked and flagged |
| E06 | INSTANCE SharedPersistence | ranked, exact | V2.1.0 values equal the fallback |
| E07 | ELEMENT id `src/services/notification` | ranked, prefix fallback | matches only `notification-service`'s source paths |
| E08 | INSTANCE with member `order-svc` | ranked, exact (alias) | old name from before the rename |
| E09 | ELEMENT `legacy-billing` | quarantined `unresolved_element` | not in the graph |
| E10 | context INTENTIONAL | skipped `intentional` | C3 judged it deliberate |
| E11 | review REJECTED | skipped `rejected` | C3's reviewer rejected it |
| E12 | SYSTEM BigBallOfMud | skipped `system_scope_not_rankable` | system-wide events are not ranked (C4-ADR-007) |
| E13 | older version of E14 | skipped `superseded` | E14's `supersedes_event_id` names it |
| E14 | current version (same `event_key`) | ranked, exact | latest version wins |
| M01–M03 | malformed | quarantined `malformed_payload` | missing `event_id`; bad `event_key`; ELEMENT scope without `element_id` |

With default settings: 17 payloads → 3 + 1 quarantined, 4 skipped, 10 eligible, 9 ranked,
resolution rate 9 / 10 = 0.9.

**C3 V2.1.0 fields.** E01, E02 and E06 carry C3's proposed `first_seen_release` and
`instance_history`, with `schema_version 2.1.0`. Today's `DegradationEventV2` ignores
them, so C4 uses the fallback. The tests that read them are skipped with the reason
"waiting for C3 V2.1.0" and switch on by themselves once C3 adds the fields to the model.
