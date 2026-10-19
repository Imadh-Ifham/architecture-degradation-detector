"""`mvp_eval`: one stored analysis run scored against the stub's ground truth (plan T-14)."""

import itertools
import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pymannkendall
import pytest
from scipy import stats
from typer.testing import CliRunner

from app.components.degradation_detection import DegradationDetectionService
from app.components.degradation_detection.config import C3Config
from app.components.degradation_detection.models import (
    InstanceTrack,
    InstanceTransition,
    Lineage,
    TrackEnd,
)
from app.components.degradation_detection.stub import StubService
from app.components.degradation_detection.stub.models import (
    FlatTruth,
    GroundTruth,
    SeriesFixture,
    TrendTruth,
)
from app.components.degradation_detection.trends.multiple_testing import benjamini_hochberg
from app.domain.analysis_run import SeriesPointRecord, StaticFlag, StoredRun
from app.domain.degradation_event import (
    DegradationEventV2,
    Lifecycle,
    Scope,
    TestMethod,
    Window,
    Worsening,
)
from scripts import c3, mvp_eval
from scripts.mvp_eval import (
    TrendOutcome,
    Verdict,
    element_ids,
    enumerated_p,
    evaluate,
    f1,
    golden_checks,
    instance_checks,
    lineage_links,
    low_confidence_check,
    oracle_p,
    p_checks_for_trends,
    q_max_delta,
    ratio,
    render,
    score_events,
    score_links,
    score_trends,
    slope_checks,
    static_comparison,
    truth_links,
)
from tests.components.degradation_detection.detection.graphs import graph_fixtures
from tests.components.degradation_detection.fakes import (
    FixedClock,
    InMemoryAnalysisRunRepository,
)
from tests.components.degradation_detection.run_records import event, trend
from tests.components.degradation_detection.stub_pipeline import ingested_stub

SERIES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "series"


@pytest.fixture(scope="module")
def truth() -> GroundTruth:
    return StubService().generate().ground_truth


@pytest.fixture(scope="module")
def stub_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The generated stub system on disk: packages and ground_truth.yaml."""
    out = tmp_path_factory.mktemp("shopfront")
    for name, text in StubService().generate().system_files.items():
        (out / name).write_text(text, encoding="utf-8", newline="\n")
    return out


def series_fixtures() -> list[SeriesFixture]:
    return [
        SeriesFixture.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(SERIES_DIR.glob("*.json"))
    ]


def ev(scope: Scope, anti_pattern_type: str, **changes: Any) -> DegradationEventV2:
    fields: dict[str, Any] = {
        "event_id": f"DEG-{anti_pattern_type}-{changes.get('element_id')}",
        "scope": scope,
        "anti_pattern_type": anti_pattern_type,
        "element_id": None,
        "lineage_id": None,
        "system_id": "shopfront",
    }
    return event().model_copy(update=fields | changes)


def hub(element_id: str) -> DegradationEventV2:
    return ev(Scope.ELEMENT, "HubLikeElement", element_id=element_id)


S1_MEMBERS = ["inventory", "notification", "order-service", "payment", "shipping"]


# --- ratios -------------------------------------------------------------------------------------


def test_ratio_is_none_when_undefined() -> None:
    assert ratio(3, 4) == 0.75
    assert ratio(0, 4) == 0.0
    assert ratio(0, 0) is None


def test_f1_is_the_harmonic_mean_and_none_when_undefined() -> None:
    assert f1(1.0, 0.5) == pytest.approx(2 / 3)
    assert f1(0.0, 0.0) is None
    assert f1(None, 1.0) is None


# --- events -------------------------------------------------------------------------------------


def test_expected_event_is_a_hit(truth: GroundTruth) -> None:
    score = score_events([hub("catalog")], truth)

    [scored] = score.events
    assert (scored.verdict, scored.scenario, scored.subject) == (Verdict.HIT, "S2", "catalog")
    assert score.hit == ("S2",)
    assert score.precision == 1.0


def test_no_events_misses_every_required_scenario(truth: GroundTruth) -> None:
    score = score_events([], truth)

    assert score.missed == ("S1", "S2", "S5", "S7", "S8")
    assert score.optional_missed == ("S9",)
    assert score.recall == 0.0
    assert score.precision is None
    assert score.strict_precision is None
    assert score.f1 is None


def test_event_on_a_planted_non_event_is_a_false_alarm(truth: GroundTruth) -> None:
    score = score_events([hub("legacy-auth")], truth)

    assert score.events[0].verdict is Verdict.FALSE_ALARM
    assert score.precision == 0.0


def test_event_on_an_unknown_element_is_a_false_alarm(truth: GroundTruth) -> None:
    assert score_events([hub("ghost")], truth).events[0].verdict is Verdict.FALSE_ALARM


def test_instance_event_with_one_unrelated_member_is_a_false_alarm(truth: GroundTruth) -> None:
    cycle = ev(Scope.INSTANCE, "CyclicDependency", members=["payment", "legacy-auth"])

    [scored] = score_events([cycle], truth).events

    assert scored.verdict is Verdict.FALSE_ALARM
    assert scored.subject == "{legacy-auth, payment}"


def test_event_on_a_collateral_element_is_neutral(truth: GroundTruth) -> None:
    score = score_events([ev(Scope.ELEMENT, "MetricDrift", element_id="cart")], truth)

    assert score.events[0].verdict is Verdict.NEUTRAL
    assert score.precision is None  # neither a hit nor a false alarm
    assert score.strict_precision == 0.0


def test_second_event_on_an_expected_subject_is_neutral(truth: GroundTruth) -> None:
    score = score_events([ev(Scope.SYSTEM, "BigBallOfMud"), ev(Scope.SYSTEM, "MetricDrift")], truth)

    assert [e.verdict for e in score.events] == [Verdict.HIT, Verdict.NEUTRAL]
    assert score.hit == ("S8",)
    assert (score.precision, score.strict_precision) == (1.0, 0.5)


def test_s8_accepts_metric_drift(truth: GroundTruth) -> None:
    assert score_events([ev(Scope.SYSTEM, "MetricDrift")], truth).hit == ("S8",)


def test_a_hit_of_another_type_on_an_expected_subject_is_neutral(truth: GroundTruth) -> None:
    score = score_events([ev(Scope.ELEMENT, "OversizedElement", element_id="catalog")], truth)

    assert score.events[0].verdict is Verdict.NEUTRAL
    assert score.hit == ()


def test_instance_event_matches_on_members_and_checks_the_lifecycle(truth: GroundTruth) -> None:
    growing = ev(
        Scope.INSTANCE, "CyclicDependency", members=S1_MEMBERS, lifecycle=Lifecycle.GROWING
    )
    persistent = growing.model_copy(update={"lifecycle": Lifecycle.PERSISTENT})

    [right] = score_events([growing], truth).events
    [wrong] = score_events([persistent], truth).events

    assert (right.verdict, right.scenario, right.lifecycle_ok) == (Verdict.HIT, "S1", True)
    assert (wrong.verdict, wrong.lifecycle_ok) == (Verdict.HIT, False)
    assert score_events([hub("catalog")], truth).events[0].lifecycle_ok is None


def test_an_optional_event_counts_only_when_found(truth: GroundTruth) -> None:
    shared = ev(
        Scope.INSTANCE,
        "SharedPersistence",
        members=["notification", "order-service", "payment", "reporting", "shipping"],
    )

    found = score_events([shared, hub("catalog")], truth)
    without = score_events([hub("catalog")], truth)

    assert found.hit == ("S2", "S9")
    assert found.recall == pytest.approx(2 / 6)  # 5 required + the optional one found
    assert without.recall == pytest.approx(1 / 5)


# --- trends -------------------------------------------------------------------------------------


def test_trend_outcomes(truth: GroundTruth) -> None:
    planted = (
        TrendTruth(
            scenario="S2",
            scope=Scope.ELEMENT,
            subject="catalog",
            metric="fan_in_norm",
            worsening=Worsening.INCREASE,
        ),
        TrendTruth(
            scenario="S2",
            scope=Scope.ELEMENT,
            subject="catalog",
            metric="fan_out_norm",
            worsening=Worsening.INCREASE,
        ),
        TrendTruth(
            scenario="S5",
            scope=Scope.ELEMENT,
            subject="reporting",
            metric="size_rz",
            worsening=Worsening.INCREASE,
        ),
    )
    flat = (
        FlatTruth(scenario="S3", scope=Scope.ELEMENT, subject="legacy-auth", metric="fan_in"),
        FlatTruth(scenario="S3", scope=Scope.ELEMENT, subject="legacy-auth", metric="size_rz"),
        FlatTruth(scenario="S6", scope=Scope.ELEMENT, subject="search", metric="size"),
    )
    small = truth.model_copy(update={"expected_trends": planted, "expected_flat": flat})
    subjects = {
        (Scope.ELEMENT, "catalog"): "LIN-catalog",
        (Scope.ELEMENT, "legacy-auth"): "LIN-legacy-auth",
        (Scope.ELEMENT, "search"): "LIN-search",
    }
    trends = [
        trend(subject_id="LIN-catalog", metric="fan_in_norm", q_value=0.01),
        trend(subject_id="LIN-catalog", metric="fan_out_norm", is_significant=False, q_value=0.2),
        trend(subject_id="LIN-legacy-auth", metric="fan_in", q_value=0.03),
        trend(subject_id="LIN-search", metric="size", is_significant=False, q_value=0.9),
    ]

    score = score_trends(small, trends, (), subjects)

    assert [r.outcome for r in score.rows] == [
        TrendOutcome.TP,
        TrendOutcome.FN,
        TrendOutcome.FN,  # reporting has no lineage: missing counts against recall
        TrendOutcome.FP,
        TrendOutcome.UNTESTED,  # flat series not tested: excluded, not a true negative
        TrendOutcome.TN,
    ]
    assert score.rows[2].note == "no series"
    assert (score.precision, score.recall) == (0.5, pytest.approx(1 / 3))


def test_a_significant_improving_planted_trend_is_a_miss(truth: GroundTruth) -> None:
    [planted] = [t for t in truth.expected_trends if t.metric == "fan_in_norm"]
    small = truth.model_copy(update={"expected_trends": (planted,), "expected_flat": ()})

    score = score_trends(
        small,
        [trend(subject_id="L", metric="fan_in_norm", is_worsening=False)],
        (),
        {(Scope.ELEMENT, "catalog"): "L"},
    )

    assert score.rows[0].outcome is TrendOutcome.FN


# --- Sen's slope ---------------------------------------------------------------------------------


def test_slope_checks_cover_the_planted_slope_fixtures() -> None:
    fixtures = series_fixtures()

    checks = slope_checks(fixtures)

    assert {c.name for c in checks} == {f.name for f in fixtures if f.planted_slope is not None}
    [exact] = [c for c in checks if c.name == "rising_exact"]
    assert exact.abs_error == pytest.approx(0, abs=1e-12)
    for c in checks:
        assert c.oracle_delta == pytest.approx(0, abs=1e-12), c.name


# --- Mann-Kendall and BH against the oracles ----------------------------------------------------


def test_enumerated_p_matches_scipy_exact_without_ties() -> None:
    values = [3.0, 1.0, 4.0, 1.5, 5.0, 9.0, 2.0]

    expected = stats.kendalltau(np.arange(7), values, method="exact").pvalue

    assert enumerated_p(values) == pytest.approx(expected, abs=1e-12)


def test_enumerated_p_with_ties_by_hand() -> None:
    # Orderings of {1, 1, 2}: S = 2, 0, -2, each twice. |S| >= 2 in four of six.
    assert enumerated_p([1.0, 1.0, 2.0]) == pytest.approx(4 / 6)


def test_oracle_p_per_method() -> None:
    values = [1.0, 2.0, 2.0, 3.0, 5.0, 4.0, 6.0, 8.0, 7.0, 9.0, 11.0]
    tie_free = [1.0, 3.0, 2.0, 4.0, 6.0, 5.0]

    assert oracle_p(tie_free, TestMethod.EXACT) == pytest.approx(
        stats.kendalltau(np.arange(6), tie_free, method="exact").pvalue
    )
    assert oracle_p(values, TestMethod.NORMAL) == pytest.approx(
        pymannkendall.original_test(values).p
    )
    assert oracle_p(values[:6], TestMethod.PERMUTATION) == enumerated_p(values[:6])


def test_permutation_has_no_oracle_above_nine_points() -> None:
    assert oracle_p([float(v) for v in range(10)], TestMethod.PERMUTATION) is None


def test_a_constant_series_has_no_oracle() -> None:
    assert oracle_p([2.0, 2.0, 2.0], TestMethod.DEGENERATE) is None


def test_p_checks_compare_the_stored_p_with_the_oracle() -> None:
    points = tuple(
        SeriesPointRecord(ordinal=i, release_id=f"v{i}", value=v)
        for i, v in enumerate([1.0, None, 3.0, 2.0, 5.0, 6.0])
    )
    values = [1.0, 3.0, 2.0, 5.0, 6.0]
    oracle = stats.kendalltau(np.arange(5), values, method="exact").pvalue
    stored = trend(points=points, n=5, p_value=round(oracle, 3), method=TestMethod.EXACT)

    [check] = p_checks_for_trends([stored], n_perm=20000)

    assert check.n == 5
    assert check.oracle_p == pytest.approx(oracle)
    assert check.delta == pytest.approx(abs(round(oracle, 3) - oracle))
    assert check.mc_se is None


def test_permutation_check_reports_the_monte_carlo_standard_error() -> None:
    points = tuple(
        SeriesPointRecord(ordinal=i, release_id=f"v{i}", value=v)
        for i, v in enumerate([1.0, 1.0, 2.0, 3.0, 3.0])
    )
    stored = trend(points=points, n=5, p_value=0.1, method=TestMethod.PERMUTATION)

    [check] = p_checks_for_trends([stored], n_perm=10000)

    p = enumerated_p([1.0, 1.0, 2.0, 3.0, 3.0])
    assert check.mc_se == pytest.approx((p * (1 - p) / 10000) ** 0.5)


def test_q_max_delta_is_zero_for_bh_q_values_and_none_without_trends() -> None:
    p = [0.01, 0.04, 0.03, 0.5]
    right = [trend(p_value=pv, q_value=qv) for pv, qv in zip(p, benjamini_hochberg(p), strict=True)]
    wrong = [*right[:-1], trend(p_value=0.5, q_value=0.4)]

    assert q_max_delta(right) == pytest.approx(0, abs=1e-15)
    assert q_max_delta(wrong) == pytest.approx(0.1)
    assert q_max_delta([]) is None


# --- golden fixtures -----------------------------------------------------------------------------


def test_every_golden_fixture_passes() -> None:
    score = golden_checks(graph_fixtures())

    assert len(score.fixtures) == len(graph_fixtures())
    assert all(f.passed for f in score.fixtures)
    assert all(d.fp == d.fn == 0 for d in score.detectors)
    assert sum(d.tp for d in score.detectors) == sum(f.expected for f in score.fixtures)


def test_a_golden_fixture_with_a_wrong_expectation_fails(tmp_path: Path) -> None:
    [source] = [p for p in graph_fixtures() if p.name == "HubLikeElement__positive_01.json"]
    data = json.loads(source.read_text(encoding="utf-8"))
    data["expected"] = []
    broken = tmp_path / source.name
    broken.write_text(json.dumps(data), encoding="utf-8")

    score = golden_checks([broken])

    [fixture] = score.fixtures
    assert not fixture.passed
    [hub_count] = [d for d in score.detectors if d.detector == "HubLikeElement"]
    assert (hub_count.tp, hub_count.fp, hub_count.fn) == (0, 1, 0)


# --- element and instance identity ---------------------------------------------------------------


def test_truth_links_follow_ids_and_the_rename(truth: GroundTruth, stub_dir: Path) -> None:
    links = truth_links(truth, element_ids(truth, stub_dir))

    assert len(links) == 15 * 9
    assert ("v1.3.0", "order-svc", "v1.4.0", "order-service") in links
    assert ("v1.3.0", "order-svc", "v1.4.0", "order-svc") not in links


def lineage(element_id: str, releases: Mapping[str, str]) -> Lineage:
    return Lineage.model_validate(
        {
            "lineage_id": f"LIN-{element_id}",
            "kind": "service",
            "members": [
                {"ordinal": i, "release_id": r, "element_id": e}
                for i, (r, e) in enumerate(releases.items())
            ],
        }
    )


def test_lineage_links_are_consecutive_members() -> None:
    lin = lineage("a", {"v1": "a", "v2": "b", "v3": "b"})

    assert lineage_links([lin]) == {("v1", "a", "v2", "b"), ("v2", "b", "v3", "b")}


def test_score_links_counts_correct_wrong_and_renames(truth: GroundTruth) -> None:
    expected = {("v1.3.0", "order-svc", "v1.4.0", "order-service"), ("v1", "x", "v2", "x")}
    predicted = {("v1", "x", "v2", "x"), ("v1", "y", "v2", "z")}

    score = score_links(truth, expected, predicted)

    assert (score.truth, score.correct, score.wrong) == (2, 1, 1)
    assert (score.renames, score.renames_correct) == (1, 0)
    assert (score.precision, score.recall) == (0.5, 0.5)


def track(
    type_: str, members: Mapping[str, list[str]], ordinals: Mapping[str, int]
) -> InstanceTrack:
    occurrences = [
        {
            "ordinal": ordinals[r],
            "release_id": r,
            "local_instance_id": f"{type_}:{min(m)}",
            "members": m,
            "member_lineages": [f"LIN-{x}" for x in m],
            "transition": InstanceTransition.PERSISTED,
        }
        for r, m in members.items()
    ]
    first = next(iter(members))
    return InstanceTrack.model_validate(
        {
            "track_id": f"AP-{type_}@{first}",
            "anti_pattern_type": type_,
            "catalog": "universal",
            "scope": Scope.INSTANCE,
            "occurrences": occurrences,
            "end": TrackEnd.OPEN,
            "lifecycle": Lifecycle.PERSISTENT,
        }
    )


def planted_tracks(truth: GroundTruth) -> list[InstanceTrack]:
    ordinals = {r.release_id: i for i, r in enumerate(truth.releases)}
    return [
        track(i.anti_pattern_type, {r: list(m) for r, m in i.members_by_release.items()}, ordinals)
        for i in truth.instances
    ]


def test_planted_instances_tracked_exactly(truth: GroundTruth) -> None:
    checks = instance_checks(truth, planted_tracks(truth))

    assert [(c.scenario, c.occurrences, c.links, c.one_track) for c in checks] == [
        ("S1", 9, 8, True),
        ("S9", 8, 7, True),
    ]
    assert all(c.occurrences_correct == c.occurrences and c.links_kept == c.links for c in checks)


def test_a_split_track_loses_one_link(truth: GroundTruth) -> None:
    ordinals = {r.release_id: i for i, r in enumerate(truth.releases)}
    [s1] = [i for i in truth.instances if i.scenario == "S1"]
    by_release = {r: list(m) for r, m in s1.members_by_release.items()}
    releases = list(by_release)
    before = {r: by_release[r] for r in releases[:3]}
    after = {r: by_release[r] for r in releases[3:]}
    after[releases[5]] = ["inventory", "payment"]  # wrong members in one release

    [check] = [
        c
        for c in instance_checks(
            truth,
            [
                track("CyclicDependency", before, ordinals),
                track("CyclicDependency", after, ordinals),
            ],
        )
        if c.scenario == "S1"
    ]

    assert (check.occurrences_correct, check.links_kept, check.one_track) == (8, 5, False)


# --- static baseline and planted ingestion scenarios ---------------------------------------------


def flag(element_id: str, metric: str, value: float, threshold: float) -> StaticFlag:
    return StaticFlag(
        release_id="v1.9.0", element_id=element_id, metric=metric, value=value, threshold=threshold
    )


def test_static_comparison_counts_avoided_false_positives(truth: GroundTruth) -> None:
    flags = [flag("legacy-auth", "fan_in", 11, 10), flag("reporting", "size", 30000, 10000)]
    events = [ev(Scope.ELEMENT, "OversizedElement", element_id="reporting")]

    score = static_comparison(flags, events, truth)

    assert [(r.element_id, r.c3_events, r.planted) for r in score.rows] == [
        ("legacy-auth", 0, "non-event (S3)"),
        ("reporting", 1, "expected event (S5)"),
    ]
    assert [(n.element_id, n.flagged, n.c3_events) for n in score.non_events] == [
        ("legacy-auth", True, 0),
        ("search", False, 0),
    ]
    assert score.avoided == 1


def test_low_confidence_release_is_listed_in_covering_windows(truth: GroundTruth) -> None:
    releases = [r.release_id for r in truth.releases]
    covering = event().model_copy(
        update={
            "window": Window(
                start_release="v1.0.0",
                end_release="v1.9.0",
                n_releases=10,
                low_confidence_releases=["v1.5.0"],
            )
        }
    )
    unlisted = covering.model_copy(
        update={"window": covering.window.model_copy(update={"low_confidence_releases": []})}
    )
    later = covering.model_copy(
        update={"window": Window(start_release="v1.6.0", end_release="v1.9.0", n_releases=4)}
    )

    assert low_confidence_check([covering, unlisted, later], truth, releases) == (2, 1)


# --- end to end on the stub ----------------------------------------------------------------------


@dataclass(frozen=True)
class Completed:
    stored: StoredRun
    artifacts: dict[str, Any]
    runs: InMemoryAnalysisRunRepository


@pytest.fixture(scope="module")
def completed() -> Completed:
    runs = InMemoryAnalysisRunRepository()
    service = DegradationDetectionService(
        ingested_stub(), runs, FixedClock(), C3Config(), new_run_id=lambda: "RUN-eval"
    )
    stored = service.run("shopfront", code_version="test-sha").stored
    return Completed(stored, runs.artifacts["RUN-eval"], runs)


def test_stub_run_scores(completed: Completed, truth: GroundTruth, stub_dir: Path) -> None:
    ev_ = evaluate(
        completed.stored, completed.artifacts, truth, stub_dir, series_fixtures(), graph_fixtures()
    )

    assert ev_.events.hit == ("S1", "S2", "S5", "S7", "S8", "S9")
    assert (ev_.events.missed, ev_.events.optional_missed) == ((), ())
    assert [e for e in ev_.events.events if e.verdict is Verdict.FALSE_ALARM] == []
    assert (ev_.events.precision, ev_.events.recall) == (1.0, 1.0)
    assert ev_.events.strict_precision == pytest.approx(6 / 16)
    assert all(e.lifecycle_ok is not False for e in ev_.events.events)
    assert {r.outcome for r in ev_.trends.rows if r.expected == "worsening"} == {TrendOutcome.TP}
    assert {r.outcome for r in ev_.trends.rows if r.expected == "flat"} == {TrendOutcome.TN}
    assert all(f.passed for f in ev_.golden.fixtures)
    assert (ev_.links.correct, ev_.links.truth, ev_.links.wrong) == (135, 135, 0)
    assert (ev_.links.renames_correct, ev_.links.renames) == (1, 1)
    assert all(c.one_track for c in ev_.instances)
    assert ev_.static.avoided == 2
    assert ev_.low_confidence[0] == ev_.low_confidence[1] > 0
    assert ev_.rejected_absent


def test_stub_run_agrees_with_the_oracles(
    completed: Completed, truth: GroundTruth, stub_dir: Path
) -> None:
    ev_ = evaluate(
        completed.stored, completed.artifacts, truth, stub_dir, series_fixtures(), graph_fixtures()
    )
    checks = [*ev_.p_trends, *ev_.p_fixtures]

    assert {c.method for c in ev_.p_trends} >= {TestMethod.NORMAL, TestMethod.PERMUTATION}
    for c in checks:
        if c.method is TestMethod.DEGENERATE:
            assert (c.p, c.oracle_p) == (1.0, None), c.label
            continue
        assert c.delta is not None, c.label
        if c.method is TestMethod.PERMUTATION:
            assert c.mc_se is not None
            assert c.delta <= 4 * c.mc_se + 1e-4, c.label
        else:
            assert c.delta <= 1e-12, c.label
    assert ev_.q_delta is not None
    assert ev_.q_delta <= 1e-12


def test_report_states_the_run_and_the_caveat(
    completed: Completed, truth: GroundTruth, stub_dir: Path
) -> None:
    text = render(
        evaluate(
            completed.stored,
            completed.artifacts,
            truth,
            stub_dir,
            series_fixtures(),
            graph_fixtures(),
        )
    )

    run = completed.stored.run
    assert text.startswith("# MVP evaluation")
    for needle in (run.run_id, run.config_hash, "test-sha", "development fixture", "S3", "S6"):
        assert needle in text
    assert "\r" not in text


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, completed: Completed, tmp_path: Path) -> Path:
    monkeypatch.setattr(c3, "run_repository", lambda: completed.runs)
    monkeypatch.setattr(c3, "OUT_DIR", tmp_path / "out")
    return tmp_path / "out"


def test_cli_writes_the_report_and_is_repeatable(cli: Path, stub_dir: Path) -> None:
    args = ["--run-id", "RUN-eval", "--truth", str(stub_dir / "ground_truth.yaml")]

    first = CliRunner().invoke(mvp_eval.app, args)
    written = (cli / "RUN-eval" / "mvp_eval.md").read_bytes()
    second = CliRunner().invoke(mvp_eval.app, args)

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert "events: 6 hits, 0 missed, 0 false alarms" in first.stdout
    assert (cli / "RUN-eval" / "mvp_eval.md").read_bytes() == written


def test_cli_unknown_run_fails(cli: Path, stub_dir: Path) -> None:
    result = CliRunner().invoke(
        mvp_eval.app, ["--run-id", "RUN-nope", "--truth", str(stub_dir / "ground_truth.yaml")]
    )

    assert result.exit_code == 1
    assert "no analysis run 'RUN-nope'" in result.stdout


def test_cli_rejects_ground_truth_of_another_system(
    cli: Path, stub_dir: Path, tmp_path: Path
) -> None:
    other = tmp_path / "other"
    shutil.copytree(stub_dir, other)
    path = other / "ground_truth.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("system_id: shopfront", "system_id: elsewhere"),
        encoding="utf-8",
    )

    result = CliRunner().invoke(mvp_eval.app, ["--run-id", "RUN-eval", "--truth", str(path)])

    assert result.exit_code == 1
    assert "elsewhere" in result.stdout


def test_enumeration_covers_every_ordering() -> None:
    """Guard on the oracle itself: the count of orderings is n!, ties included."""
    values = [2.0, 1.0, 2.0, 3.0]
    s = sum(np.sign(values[j] - values[i]) for i, j in itertools.combinations(range(4), 2))
    hits = sum(
        abs(sum(np.sign(o[j] - o[i]) for i, j in itertools.combinations(range(4), 2))) >= abs(s)
        for o in itertools.permutations(values)
    )

    assert enumerated_p(values) == pytest.approx(hits / 24)
