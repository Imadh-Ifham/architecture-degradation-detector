# Checks the hand-designed C4 fixtures do what fixture_expected.json says they do,
# so later tasks can assert against that file. See tests/fixtures/degradation_scoring/README.md.

import json
import logging
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
import pytest
from pydantic import ValidationError

from app.domain.boundary import UNKNOWN_FIELD_IGNORED
from app.domain.degradation_event import DegradationEventV2
from app.domain.release_package import ReleasePackageV1

BACKEND = Path(__file__).resolve().parents[3]
FIXTURES = BACKEND / "tests" / "fixtures" / "degradation_scoring"
AHP_FILE = BACKEND / "app/components/degradation_scoring/scoring_engine/weights/ahp_v1.json"

V2_1_PENDING = pytest.mark.skipif(
    "first_seen_release" not in DegradationEventV2.model_fields,
    reason="waiting for C3 V2.1.0",
)


def load(relative: str) -> Any:
    return json.loads((FIXTURES / relative).read_text(encoding="utf-8"))


EXPECTED: dict[str, Any] = load("fixture_expected.json")
PAYLOADS: list[dict[str, Any]] = load("events/fixture_events.v1.json")
PACKAGE = ReleasePackageV1.model_validate(load("graphs/fixture_release_package.v1.5.0.json"))
MALFORMED_INDEXES = {row["index"] for row in EXPECTED["malformed"]}
VALID = [p for i, p in enumerate(PAYLOADS) if i not in MALFORMED_INDEXES]
BY_ID = {row["event_id"]: row for row in EXPECTED["events"]}


def graph() -> "nx.DiGraph[str]":
    g: nx.DiGraph[str] = nx.DiGraph()
    g.add_nodes_from(element.id for element in PACKAGE.elements)
    g.add_edges_from((dep.from_, dep.to) for dep in PACKAGE.dependencies)
    return g


def fallback_first_seen(event: DegradationEventV2) -> str:
    return event.window.start_release


def fallback_presence(event: DegradationEventV2) -> list[str]:
    return [p.release_id for p in event.affected_metrics[0].series if p.value is not None]


# --- events -------------------------------------------------------------------------------


def test_every_valid_payload_parses_and_has_a_designed_outcome() -> None:
    events = [DegradationEventV2.model_validate(p) for p in VALID]

    assert sorted(e.event_id for e in events) == sorted(BY_ID)
    for event in events:
        row = BY_ID[event.event_id]
        assert event.review_status == row["review_status"]
        assert event.context.tag == row["context_tag"]


@pytest.mark.parametrize("row", EXPECTED["malformed"], ids=lambda row: row["defect"])
def test_malformed_payload_fails_with_its_designed_error(row: dict[str, Any]) -> None:
    with pytest.raises(ValidationError) as caught:
        DegradationEventV2.model_validate(PAYLOADS[row["index"]])

    errors = caught.value.errors()
    assert [(e["type"], list(e["loc"])) for e in errors] == [(row["error_type"], row["loc"])]


def test_designed_counts_add_up() -> None:
    counts = EXPECTED["counts"]
    outcomes = [row["outcome"] for row in EXPECTED["events"]]
    skipped = {o.split(":")[1]: outcomes.count(o) for o in outcomes if o.startswith("skipped")}
    resolution = [row["resolution"] for row in EXPECTED["events"] if row["resolution"]]

    assert counts["payloads"] == len(PAYLOADS)
    assert counts["quarantined"]["malformed_payload"] == len(MALFORMED_INDEXES)
    assert counts["quarantined"]["unresolved_element"] == resolution.count("unresolved")
    assert counts["skipped"] == skipped
    assert counts["ranked"] == outcomes.count("ranked")
    assert counts["eligible"] == len(resolution)
    assert counts["resolution_rate"] == (len(resolution) - resolution.count("unresolved")) / len(
        resolution
    )


def test_superseded_event_is_named_by_its_successor() -> None:
    events = {e.event_id: e for e in map(DegradationEventV2.model_validate, VALID)}
    superseded = {e.supersedes_event_id for e in events.values()} - {None}

    assert superseded == {k for k, row in BY_ID.items() if row["outcome"] == "skipped:superseded"}
    for old in superseded:
        successor = next(e for e in events.values() if e.supersedes_event_id == old)
        assert successor.event_key == events[str(old)].event_key


# --- resolution ---------------------------------------------------------------------------


def test_designed_resolution_matches_the_graph() -> None:
    ids = {element.id for element in PACKAGE.elements}
    aliases = {alias for element in PACKAGE.elements for alias in element.aliases}
    paths = [p for e in PACKAGE.elements for p in e.extra.get("source_paths", [])]

    for event in map(DegradationEventV2.model_validate, VALID):
        designed = BY_ID[event.event_id]["resolution"]
        if designed is None:
            continue
        names = [event.element_id] if event.element_id else event.members
        if designed == "exact":
            assert all(name in ids | aliases for name in names), event.event_id
        elif designed == "prefix_fallback":
            assert all(n not in ids | aliases for n in names)
            assert all(any(p.startswith(f"{n}/") for p in paths) for n in names)
        else:
            assert all(n not in ids | aliases for n in names)
            assert not any(p.startswith(f"{n}/") for n in names for p in paths)


# --- fallback and C3 V2.1.0 values ----------------------------------------------------------


def test_fallback_values_match_the_design() -> None:
    for event in map(DegradationEventV2.model_validate, VALID):
        designed = BY_ID[event.event_id]["fallback"]
        assert fallback_first_seen(event) == designed["first_seen_release"], event.event_id
        assert fallback_presence(event) == designed["releases_present"], event.event_id


def test_v2_1_events_differ_from_their_fallback_where_designed() -> None:
    rows = [row for row in EXPECTED["events"] if "c3_v2_1" in row]
    differs = {
        row["event_id"]: row["c3_v2_1"] != row["fallback"] for row in rows
    }  # E01 first-seen, E02 overcount, E06 agrees

    assert list(differs.values()) == [True, True, False]


@pytest.mark.skipif(
    "first_seen_release" in DegradationEventV2.model_fields,
    reason="C3 V2.1.0 is merged; the fields are read, not ignored",
)
def test_v2_1_fields_are_ignored_today_so_c4_falls_back(caplog: pytest.LogCaptureFixture) -> None:
    payload = next(p for p in VALID if "first_seen_release" in p)

    with caplog.at_level(logging.WARNING):
        event = DegradationEventV2.model_validate(payload)

    assert not hasattr(event, "first_seen_release")
    ignored = {
        getattr(r, "field", None) for r in caplog.records if r.message == UNKNOWN_FIELD_IGNORED
    }
    assert {"first_seen_release", "instance_history"} <= ignored


@V2_1_PENDING
def test_v2_1_first_seen_release_is_read() -> None:
    for payload in (p for p in VALID if "first_seen_release" in p):
        event = DegradationEventV2.model_validate(payload)
        designed = BY_ID[event.event_id]["c3_v2_1"]
        assert event.model_dump()["first_seen_release"] == designed["first_seen_release"]


@V2_1_PENDING
def test_v2_1_instance_history_is_read() -> None:
    for payload in (p for p in VALID if "instance_history" in p):
        event = DegradationEventV2.model_validate(payload)
        history = event.model_dump()["instance_history"]
        designed = BY_ID[event.event_id]["c3_v2_1"]
        assert [h["release_id"] for h in history] == designed["releases_present"]


# --- graph --------------------------------------------------------------------------------


def test_graph_has_the_designed_shape() -> None:
    g = graph()
    design = EXPECTED["graph"]

    assert g.number_of_nodes() == design["elements"]
    cycles = [sorted(c) for c in nx.simple_cycles(g)]
    assert cycles == [sorted(design["cycle"])]
    hub, in_degree = max(g.in_degree, key=lambda pair: pair[1])
    assert (hub, in_degree) == (design["hub"], design["hub_dependents"])
    assert design["bridge"] in set(nx.articulation_points(g.to_undirected()))


def test_graph_names_paths_and_aliases_as_designed() -> None:
    design = EXPECTED["graph"]
    without_paths = sorted(e.id for e in PACKAGE.elements if not e.extra.get("source_paths"))
    aliases = {e.id: e.aliases[0] for e in PACKAGE.elements if e.aliases}

    assert without_paths == sorted(design["without_source_paths"])
    assert aliases == design["renamed"]
    assert PACKAGE.system_id == EXPECTED["system_id"]
    assert PACKAGE.release_id == EXPECTED["release_id"]


# --- ADRs and AHP -------------------------------------------------------------------------


def front_matter(path: Path) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.DOTALL)
    assert match, path.name
    return dict(line.split(": ", 1) for line in match.group(1).splitlines())


def test_adrs_cover_three_status_and_scope_combinations() -> None:
    combos = sorted(
        (meta["status"], meta["scope"])
        for meta in map(front_matter, sorted((FIXTURES / "adr").glob("*.md")))
    )
    linked = sorted(i.ref for i in PACKAGE.intent if i.ref)

    assert combos == [("accepted", "system"), ("proposed", "local"), ("superseded", "component")]
    assert linked == sorted(f"adr/{p.name}" for p in (FIXTURES / "adr").glob("*.md"))


def test_provisional_ahp_matrix_is_reciprocal_and_consistent() -> None:
    ahp = json.loads(AHP_FILE.read_text(encoding="utf-8"))
    matrix = [[Fraction(cell) for cell in row] for row in ahp["matrix"]]
    n = len(matrix)

    assert ahp["provenance"] == "provisional-author-elicited"
    assert ahp["criteria"] == ["blast_radius", "hotspot", "adr_violation", "persistence"]
    assert all(matrix[i][j] * matrix[j][i] == 1 for i in range(n) for j in range(n))
    # CR = ((lambda_max - n) / (n - 1)) / RI(4 = 0.90); hand check: lambda_max = 4.031.
    lambda_max = max(np.linalg.eigvals(np.array(matrix, dtype=float)).real)
    assert round((lambda_max - n) / (n - 1) / 0.90, 2) == 0.01


def test_readme_names_every_fixture_file() -> None:
    readme = (FIXTURES / "README.md").read_text(encoding="utf-8")
    files = [p for p in FIXTURES.rglob("*") if p.is_file() and p.name != "README.md"]

    assert files
    for path in files:
        name = path.relative_to(FIXTURES).as_posix()
        assert name in readme or path.parent.name == "adr", name
