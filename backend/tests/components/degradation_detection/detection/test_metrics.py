"""M2 step 2: element and system metrics of one release (pure).

Expected values are worked out by hand from the definitions in the plan (Section 4, M2), so a
failure points at the definition, not at a library.
"""

from collections.abc import Iterable

import pytest
from structlog.testing import capture_logs

from app.components.degradation_detection.config import MetricsConfig
from app.components.degradation_detection.detection.graph_builder import build_graph
from app.components.degradation_detection.detection.metric_registry import MetricRegistry
from app.components.degradation_detection.detection.metrics import (
    compute_metrics,
    count_anti_patterns,
)
from app.components.degradation_detection.models import AntiPatternInstance, MetricObservation
from app.domain.canonical_release import CanonicalRelease
from app.domain.degradation_event import Scope
from tests.components.degradation_detection.detection.graphs import TWO_TRIANGLES, release

MAD_TO_SIGMA = 1.4826
REGISTRY = MetricRegistry.from_config(MetricsConfig())


def observe(r: CanonicalRelease, registry: MetricRegistry = REGISTRY) -> list[MetricObservation]:
    return list(compute_metrics(build_graph(r), registry))


def per_element(observations: Iterable[MetricObservation], metric: str) -> dict[str, float | None]:
    return {o.element_id: o.value for o in observations if o.metric == metric and o.element_id}


def system(observations: Iterable[MetricObservation]) -> dict[str, float | None]:
    return {o.metric: o.value for o in observations if o.element_id is None}


# --- coupling ---------------------------------------------------------------------------------


def test_fan_counts_distinct_neighbours_not_edge_counts() -> None:
    obs = observe(release("abcd", [("a", "b"), ("a", "c"), ("d", "b")], counts={("a", "b"): 3}))

    assert per_element(obs, "fan_out") == {"a": 2.0, "b": 0.0, "c": 0.0, "d": 1.0}
    assert per_element(obs, "fan_in") == {"a": 0.0, "b": 2.0, "c": 1.0, "d": 0.0}


def test_normalised_fan_divides_by_n_minus_one() -> None:
    obs = observe(release("abcd", [("a", "b"), ("a", "c"), ("d", "b")]))

    assert per_element(obs, "fan_out_norm")["a"] == pytest.approx(2 / 3)
    assert per_element(obs, "fan_in_norm")["b"] == pytest.approx(2 / 3)


def test_single_element_release_has_null_normalised_fan() -> None:
    obs = observe(release(["only"]))

    assert per_element(obs, "fan_in_norm") == {"only": None}
    assert per_element(obs, "fan_out_norm") == {"only": None}


def test_isolated_element_has_null_instability_but_zero_fan() -> None:
    obs = observe(release(["a", "b", "lonely"], [("a", "b")]))

    assert per_element(obs, "instability") == {"a": 1.0, "b": 0.0, "lonely": None}
    assert per_element(obs, "fan_in")["lonely"] == 0.0


def test_unstable_dep_ratio_is_the_share_of_out_deps_on_less_stable_elements() -> None:
    # I(s) = 2 / (3 + 2) = 0.4. s depends on u (I = 2/3, less stable: bad) and v (I = 0: fine).
    edges = [("p", "s"), ("q", "s"), ("r", "s"), ("s", "u"), ("s", "v"), ("u", "t1"), ("u", "t2")]

    ratio = per_element(
        observe(release(["p", "q", "r", "s", "u", "v", "t1", "t2"], edges)), "unstable_dep_ratio"
    )

    assert ratio["s"] == pytest.approx(0.5)
    assert ratio["p"] == 0.0  # I(p) = 1: nothing is less stable
    assert ratio["v"] is None  # no out-deps: 0/0


def test_equal_instability_is_not_less_stable() -> None:
    # I(a) = 1/2 and I(b) = 2/4: the same number, so a -> b is not an unstable dependency.
    edges = [("x", "a"), ("a", "b"), ("y", "b"), ("b", "z1"), ("b", "z2")]

    ratio = per_element(
        observe(release(["x", "a", "b", "y", "z1", "z2"], edges)), "unstable_dep_ratio"
    )

    assert ratio["a"] == 0.0


# --- size -------------------------------------------------------------------------------------


def test_size_rz_is_robust_z_within_the_release() -> None:
    sizes: dict[str, float | None] = {"a": 10, "b": 20, "c": 30, "d": 40, "e": 1000}

    obs = observe(release("abcde", sizes=sizes))

    # median 30, absolute deviations 20 10 0 10 970 -> MAD 10
    scale = MAD_TO_SIGMA * 10
    assert per_element(obs, "size_rz") == pytest.approx(
        {"a": -20 / scale, "b": -10 / scale, "c": 0.0, "d": 10 / scale, "e": 970 / scale}
    )
    assert per_element(obs, "size")["e"] == 1000.0


def test_size_rz_is_null_for_every_element_when_mad_is_zero() -> None:
    obs = observe(release("abcd", sizes={"a": 5, "b": 5, "c": 5, "d": 100}))

    assert per_element(obs, "size_rz") == {"a": None, "b": None, "c": None, "d": None}


def test_missing_size_stays_null_and_is_left_out_of_the_median() -> None:
    obs = observe(release("abcde", sizes={"a": 10, "b": 20, "c": None, "d": 30, "e": 40}))

    # median of 10 20 30 40 is 25, deviations 15 5 5 15 -> MAD 10
    rz = per_element(obs, "size_rz")
    assert rz["c"] is None
    assert rz["a"] == pytest.approx(-15 / (MAD_TO_SIGMA * 10))
    assert per_element(obs, "size")["c"] is None


def test_mixed_size_units_make_size_rz_null_and_are_logged() -> None:
    r = release(
        "abc",
        sizes={"a": 10, "b": 20, "c": 300},
        size_unit={"a": "loc", "b": "loc", "c": "classes"},
    )

    with capture_logs() as logs:
        obs = observe(r)

    assert set(per_element(obs, "size_rz").values()) == {None}
    assert per_element(obs, "size")["c"] == 300.0  # the raw size is still a fact
    [entry] = [e for e in logs if e.get("reason") == "SIZE_UNIT_MIXED"]
    assert entry["units"] == ["classes", "loc"]


# --- cycles -----------------------------------------------------------------------------------


def test_scc_measures_for_one_cycle_and_a_tail() -> None:
    obs = observe(release("abcd", [("a", "b"), ("b", "c"), ("c", "a"), ("c", "d")]))

    assert per_element(obs, "scc_size") == {"a": 3.0, "b": 3.0, "c": 3.0, "d": 1.0}
    measures = system(obs)
    assert measures["scc_count"] == 1.0
    assert measures["largest_scc_size"] == 3.0
    assert measures["largest_scc_share"] == pytest.approx(3 / 4)
    assert measures["cyclic_edge_count"] == 3.0  # c -> d leaves the cycle


def test_scc_measures_for_two_cycles() -> None:
    edges = [("a", "b"), ("b", "a"), ("b", "c"), ("c", "d"), ("d", "e"), ("e", "c")]

    measures = system(observe(release("abcde", edges)))

    assert measures["scc_count"] == 2.0
    assert measures["largest_scc_size"] == 3.0
    assert measures["largest_scc_share"] == pytest.approx(3 / 5)
    assert measures["cyclic_edge_count"] == 5.0  # b -> c joins the two cycles but is in neither


def test_dag_has_no_cycles_and_zero_not_null_cycle_measures() -> None:
    obs = observe(release("abc", [("a", "b"), ("b", "c"), ("a", "c")]))

    assert per_element(obs, "scc_size") == {"a": 1.0, "b": 1.0, "c": 1.0}
    assert {k: system(obs)[k] for k in ("scc_count", "largest_scc_size", "cyclic_edge_count")} == {
        "scc_count": 0.0,
        "largest_scc_size": 0.0,
        "cyclic_edge_count": 0.0,
    }
    assert system(obs)["largest_scc_share"] == 0.0


# --- modularity -------------------------------------------------------------------------------


def test_modularity_of_two_triangles_joined_by_a_bridge() -> None:
    # Communities {a,b,c} and {d,e,f}; m = 7, each community has 3 edges and degree sum 7:
    # Q = 2 * (3/7 - (7/14)^2) = 5/14.
    assert system(observe(release("abcdef", TWO_TRIANGLES)))["modularity"] == pytest.approx(5 / 14)


def test_modularity_ignores_edge_direction_and_edge_counts() -> None:
    edges = [*TWO_TRIANGLES, ("b", "a")]  # a <-> b becomes one undirected edge

    modularity = system(observe(release("abcdef", edges, counts={("c", "d"): 100})))["modularity"]

    assert modularity == pytest.approx(5 / 14)


def test_modularity_is_deterministic_across_runs_and_input_order() -> None:
    nodes = [f"n{i:02d}" for i in range(12)]
    # A ring with chords: many equal-gain merges, so tie-breaking decides the communities.
    edges = [(nodes[i], nodes[(i + 1) % 12]) for i in range(12)]
    edges += [(nodes[i], nodes[(i + 4) % 12]) for i in range(0, 12, 3)]

    values = {
        system(observe(release(order, list(edge_order))))["modularity"]
        for order, edge_order in [
            (nodes, edges),
            (nodes, edges),
            (list(reversed(nodes)), list(reversed(edges))),
        ]
    }

    assert len(values) == 1


def test_modularity_is_null_without_edges() -> None:
    assert system(observe(release("abc")))["modularity"] is None


# --- C1 pass-through --------------------------------------------------------------------------


def test_declared_c1_metrics_pass_through_and_undeclared_ones_are_logged() -> None:
    r = release(
        "abc",
        metrics={"a": {"c1.lcom": 0.4, "c1.wmc": 7}, "b": {"c1.lcom": None}, "c": {}},
    )

    with capture_logs() as logs:
        obs = observe(r)

    assert per_element(obs, "c1.lcom") == {"a": 0.4, "b": None, "c": None}
    assert per_element(obs, "c1.wmc") == {}
    [entry] = [e for e in logs if e.get("reason") == "C1_METRIC_UNDECLARED"]
    assert entry["metrics"] == ["c1.wmc"]
    assert entry["release_id"] == "v1.0.0"


# --- registry coherence -----------------------------------------------------------------------


def test_every_declared_metric_is_computed_and_nothing_else() -> None:
    r = release("abcd", [("a", "b"), ("b", "a"), ("c", "d")], sizes={"a": 1, "b": 2, "c": 4})

    obs = observe(r)

    assert {o.metric for o in obs} == set(REGISTRY.names)
    for d in REGISTRY.element_metrics:
        assert sorted(o.element_id or "" for o in obs if o.metric == d.name) == ["a", "b", "c", "d"]
    assert len([o for o in obs if o.element_id is None]) == len(REGISTRY.system_metrics)
    assert {o.release_id for o in obs} == {"v1.0.0"}


def test_registry_without_normalised_coupling_computes_no_normalised_metric() -> None:
    registry = MetricRegistry.from_config(MetricsConfig(normalised_coupling=False))

    names = {o.metric for o in observe(release("ab", [("a", "b")]), registry)}

    assert "fan_in_norm" not in names and "fan_in" in names


def test_observations_come_out_in_a_stable_order() -> None:
    r = release("abcdef", TWO_TRIANGLES, sizes={n: float(i) for i, n in enumerate("abcdef")})

    assert observe(r) == observe(r)


# --- anti-pattern counts --------------------------------------------------------------------

AP_REGISTRY = MetricRegistry.from_config(
    MetricsConfig(), anti_pattern_types=("CyclicDependency", "HubLikeElement", "SharedPersistence")
)


def instance(anti_pattern_type: str, *members: str) -> AntiPatternInstance:
    return AntiPatternInstance(
        release_id="v1.0.0",
        local_instance_id=f"{anti_pattern_type}:{members[0]}",
        anti_pattern_type=anti_pattern_type,
        catalog="universal",
        scope=Scope.INSTANCE,
        members=members,
    )


def test_graph_metrics_leave_the_anti_pattern_counts_to_the_detectors() -> None:
    names = {o.metric for o in observe(release("ab", [("a", "b")]), AP_REGISTRY)}

    assert not any(name.startswith("ap_") for name in names)


def test_counts_per_type_zero_when_run_and_null_when_not_run() -> None:
    g = build_graph(release("abcdefg"))
    found = [instance("CyclicDependency", "a", "b"), instance("CyclicDependency", "c", "d")]

    obs = count_anti_patterns(g, AP_REGISTRY, ("CyclicDependency", "HubLikeElement"), found)

    assert system(obs) == {
        "ap_count.CyclicDependency": 2.0,
        "ap_count.HubLikeElement": 0.0,  # ran, found nothing: a real zero
        "ap_count.SharedPersistence": None,  # did not run: unknown, not zero
        "ap_involvement_share": pytest.approx(4 / 7),
    }
    assert all(o.release_id == "v1.0.0" for o in obs)


def test_involvement_counts_each_element_once() -> None:
    g = build_graph(release("abcd"))
    found = [instance("CyclicDependency", "a", "b"), instance("HubLikeElement", "b")]

    obs = count_anti_patterns(g, AP_REGISTRY, ("CyclicDependency", "HubLikeElement"), found)

    assert system(obs)["ap_involvement_share"] == pytest.approx(2 / 4)


def test_involvement_is_null_when_no_detector_ran() -> None:
    obs = count_anti_patterns(build_graph(release("ab")), AP_REGISTRY, (), [])

    assert system(obs)["ap_involvement_share"] is None


def test_a_detector_that_ran_without_a_declared_count_is_an_error() -> None:
    with pytest.raises(ValueError, match="ap_count.OversizedElement"):
        count_anti_patterns(build_graph(release("ab")), AP_REGISTRY, ("OversizedElement",), [])
