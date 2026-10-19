# Regression (C4-T11): blast radius reproduces the old prototype on its 13-module graph.
# Only its blast-radius part; its other dimensions were hardcoded stubs.

import contextlib
import io
import runpy
from typing import Any

import networkx as nx
import pytest

from app.components.degradation_scoring.features.blast_radius import (
    blast_radius,
    compute_centralities,
)
from tests.components.degradation_scoring.support import FIXTURES

PROTOTYPE = FIXTURES / "legacy" / "prototype.py"

# The prototype's graph, rebuilt edge by edge ("A depends on B", weight 1).
EDGES = [
    ("api-gateway", "auth-service"),
    ("api-gateway", "core-engine"),
    ("api-gateway", "config-manager"),
    ("auth-service", "core-engine"),
    ("auth-service", "user-store"),
    ("core-engine", "data-access"),
    ("core-engine", "event-bus"),
    ("core-engine", "config-manager"),
    ("order-service", "core-engine"),
    ("order-service", "payment-service"),
    ("order-service", "inventory-service"),
    ("payment-service", "core-engine"),
    ("payment-service", "data-access"),
    ("inventory-service", "data-access"),
    ("inventory-service", "event-bus"),
    ("notification-svc", "event-bus"),
    ("notification-svc", "user-store"),
    ("reporting-svc", "data-access"),
    ("reporting-svc", "core-engine"),
    ("scheduler", "core-engine"),
    ("scheduler", "event-bus"),
    ("data-access", "config-manager"),
    ("event-bus", "config-manager"),
    ("user-store", "data-access"),
]


@pytest.fixture(scope="module")
def prototype(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    # the prototype runs on load: it prints and writes two report files to the working
    # directory, so it runs inside a temporary folder with its output captured
    with (
        contextlib.chdir(tmp_path_factory.mktemp("prototype")),
        contextlib.redirect_stdout(io.StringIO()),
    ):
        return runpy.run_path(str(PROTOTYPE))


@pytest.fixture(scope="module")
def rebuilt() -> "nx.DiGraph[str]":
    g: nx.DiGraph[str] = nx.DiGraph()
    g.add_edges_from(EDGES, weight=1)
    return g


def test_rebuilt_graph_is_the_prototype_graph(
    prototype: dict[str, Any], rebuilt: "nx.DiGraph[str]"
) -> None:
    assert rebuilt.number_of_nodes() == 13
    assert set(rebuilt.edges) == set(prototype["G"].edges)
    # no cycle, so depth on the condensation equals the prototype's depth (C4-ADR-008)
    assert nx.is_directed_acyclic_graph(rebuilt)


def test_features_match_the_prototype_for_all_six_events(
    prototype: dict[str, Any], rebuilt: "nx.DiGraph[str]"
) -> None:
    c = compute_centralities(rebuilt, alpha=0.85, exact_max_nodes=5000, sample_k=500, seed=42)
    events = prototype["events"]

    assert [event["id"] for event in events] == [f"EVT-00{i}" for i in range(1, 7)]
    for event in events:
        ours = blast_radius(rebuilt, event["elements"], c)
        theirs = event["blast_radius"]

        # the prototype rounds to 4 d.p. (and ran PageRank at networkx's looser default tol)
        assert ours.fan_in_ratio == pytest.approx(theirs["fan_in_ratio"], abs=1e-4), event["id"]
        assert ours.pagerank == pytest.approx(theirs["pagerank_sum"], abs=1e-4), event["id"]
        assert ours.betweenness == pytest.approx(theirs["betweenness"], abs=1e-4), event["id"]
        assert ours.depth == theirs["depth"], event["id"]
