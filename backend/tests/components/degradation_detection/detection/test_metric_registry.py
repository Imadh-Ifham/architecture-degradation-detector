"""M2 step 2: every metric is declared once, with the direction in which it gets worse."""

import pytest

from app.components.degradation_detection.config import C1PassthroughMetric, MetricsConfig
from app.components.degradation_detection.detection.metric_registry import MetricRegistry
from app.components.degradation_detection.models import MetricDef, MetricLevel
from app.domain.degradation_event import Worsening

ELEMENT_METRICS = {
    "fan_in": Worsening.INCREASE,
    "fan_out": Worsening.INCREASE,
    "fan_in_norm": Worsening.INCREASE,
    "fan_out_norm": Worsening.INCREASE,
    "instability": None,  # supports detectors only
    "size": Worsening.INCREASE,
    "size_rz": Worsening.INCREASE,
    "scc_size": Worsening.INCREASE,
    "unstable_dep_ratio": Worsening.INCREASE,
    "c1.lcom": Worsening.INCREASE,  # from the default config [D-21]
}
SYSTEM_METRICS = {
    "scc_count": Worsening.INCREASE,
    "largest_scc_size": Worsening.INCREASE,
    "largest_scc_share": Worsening.INCREASE,
    "cyclic_edge_count": Worsening.INCREASE,
    "modularity": Worsening.DECREASE,
}


def test_default_registry_matches_the_plan_table() -> None:
    registry = MetricRegistry.from_config(MetricsConfig())

    assert {d.name: d.worsening for d in registry.element_metrics} == ELEMENT_METRICS
    assert {d.name: d.worsening for d in registry.system_metrics} == SYSTEM_METRICS
    assert all(d.level is MetricLevel.ELEMENT for d in registry.element_metrics)
    assert all(d.level is MetricLevel.SYSTEM for d in registry.system_metrics)


def test_c1_passthrough_metrics_take_their_direction_and_unit_from_config() -> None:
    cfg = MetricsConfig(
        c1_passthrough=(
            C1PassthroughMetric(name="c1.cohesion", unit="score", worsening=Worsening.DECREASE),
        )
    )

    registry = MetricRegistry.from_config(cfg)

    assert registry.get("c1.cohesion") == MetricDef(
        name="c1.cohesion", level=MetricLevel.ELEMENT, unit="score", worsening=Worsening.DECREASE
    )
    assert "c1.lcom" not in registry


def test_normalised_coupling_off_drops_the_normalised_metrics() -> None:
    registry = MetricRegistry.from_config(MetricsConfig(normalised_coupling=False))

    assert "fan_in_norm" not in registry and "fan_out_norm" not in registry
    assert "fan_in" in registry


def test_declaration_order_is_stable() -> None:
    first = MetricRegistry.from_config(MetricsConfig()).names
    second = MetricRegistry.from_config(MetricsConfig()).names

    assert first == second
    assert first[0] == "fan_in"


def test_a_metric_cannot_be_declared_twice() -> None:
    fan_in = MetricDef(name="fan_in", level=MetricLevel.ELEMENT, unit="count")

    with pytest.raises(ValueError, match="fan_in"):
        MetricRegistry((fan_in, fan_in))


def test_unknown_metric_is_an_error() -> None:
    with pytest.raises(KeyError, match="no_such_metric"):
        MetricRegistry.from_config(MetricsConfig()).get("no_such_metric")


# --- anti-pattern counts (declared with the detector registry, T-07) -----------------------


def test_anti_pattern_metrics_are_declared_per_type_after_the_graph_metrics() -> None:
    registry = MetricRegistry.from_config(
        MetricsConfig(), anti_pattern_types=("CyclicDependency", "SharedPersistence")
    )

    assert registry.names[-3:] == (
        "ap_count.CyclicDependency",
        "ap_count.SharedPersistence",
        "ap_involvement_share",
    )
    assert registry.get("ap_count.CyclicDependency") == MetricDef(
        name="ap_count.CyclicDependency",
        level=MetricLevel.SYSTEM,
        unit="count",
        worsening=Worsening.INCREASE,
    )
    assert registry.get("ap_involvement_share") == MetricDef(
        name="ap_involvement_share",
        level=MetricLevel.SYSTEM,
        unit="ratio",
        worsening=Worsening.INCREASE,
    )
    assert [d.name for d in registry.anti_pattern_metrics] == list(registry.names[-3:])


def test_no_anti_pattern_types_declares_no_anti_pattern_metrics() -> None:
    registry = MetricRegistry.from_config(MetricsConfig())

    assert registry.anti_pattern_metrics == ()
    assert "ap_involvement_share" not in registry
