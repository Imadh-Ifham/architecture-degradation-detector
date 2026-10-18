"""Static-threshold baseline (plan T-13): what a fixed-threshold tool would flag at the end.

It reads the same M2 observations C3 tests for trends, so the comparison with C3 differs only in
the decision rule: a fixed threshold here, a trend there.
"""

from app.components.degradation_detection.baselines import StaticBaselineService
from app.components.degradation_detection.config import (
    BaselineConfig,
    C3Config,
    StaticBaselineConfig,
    StaticRule,
)
from app.components.degradation_detection.detection import DetectionService
from app.components.degradation_detection.models import MetricObservation, ReleaseDetection
from app.domain.analysis_run import StaticFlag
from tests.components.degradation_detection.stub_pipeline import stub_run


def cfg(*rules: tuple[str, float]) -> C3Config:
    static = StaticBaselineConfig(rules=tuple(StaticRule(metric=m, above=a) for m, a in rules))
    return C3Config(baseline=BaselineConfig(static=static))


def detection(*observations: tuple[str | None, str, float | None]) -> ReleaseDetection:
    return ReleaseDetection(
        release_id="v9",
        observations=tuple(
            MetricObservation(release_id="v9", element_id=e, metric=m, value=v)
            for e, m, v in observations
        ),
    )


def test_a_value_above_the_threshold_is_flagged() -> None:
    flags = StaticBaselineService(cfg(("fan_in", 10))).flag(detection(("auth", "fan_in", 11.0)))

    assert flags == (
        StaticFlag(release_id="v9", element_id="auth", metric="fan_in", value=11.0, threshold=10),
    )


def test_a_value_at_the_threshold_is_not_flagged() -> None:
    assert StaticBaselineService(cfg(("fan_in", 10))).flag(detection(("a", "fan_in", 10.0))) == ()


def test_null_is_never_flagged() -> None:
    """Null stays null: an unmeasured value is not above anything."""
    assert StaticBaselineService(cfg(("size", 1))).flag(detection(("a", "size", None))) == ()


def test_system_metrics_and_unlisted_metrics_are_ignored() -> None:
    observed = detection((None, "fan_in", 99.0), ("a", "fan_out", 99.0))

    assert StaticBaselineService(cfg(("fan_in", 10))).flag(observed) == ()


def test_every_rule_is_applied_and_flags_are_sorted_by_element_then_metric() -> None:
    observed = detection(
        ("b", "size", 20000.0),
        ("a", "size", 12000.0),
        ("b", "fan_in", 12.0),
        ("c", "fan_in", 3.0),
    )

    flags = StaticBaselineService(cfg(("size", 10000), ("fan_in", 10))).flag(observed)

    assert [(f.element_id, f.metric) for f in flags] == [
        ("a", "size"),
        ("b", "fan_in"),
        ("b", "size"),
    ]


def test_no_rules_flag_nothing() -> None:
    assert StaticBaselineService(cfg()).flag(detection(("a", "fan_in", 99.0))) == ()


def test_stub_static_thresholds_flag_the_planted_non_events() -> None:
    """Every expected non-event of the stub is flagged by the rule its manifest names."""
    run = stub_run()
    last = run.timeline.entries[-1].release

    flags = StaticBaselineService(run.cfg).flag(DetectionService(run.cfg).detect(last))

    flagged = {(f.element_id, f"{f.metric} > {f.threshold:g}") for f in flags}
    for non_event in run.truth.expected_non_events:
        assert (non_event.element_id, non_event.static_flag) in flagged
