"""TrendService on the synthetic stub: T-12 acceptance (plan Section 6.3).

Planted worsening trends come out significant and worsening; flat and noisy ones do not;
S1, S2, S5, S7, S8 and S9 give candidates; S3 and S6 give none; every candidate is on a
scenario subject or a collateral element (stub/models.py says how to score).
"""

import pytest

from app.components.degradation_detection.models import TrendResult
from app.components.degradation_detection.trends import TrendService
from app.components.degradation_detection.trends.candidates import METRIC_DRIFT
from app.components.degradation_detection.trends.models import (
    NO_WORSENING_DIRECTION,
    SERIES_TOO_SHORT,
)
from app.domain.degradation_event import Scope
from tests.components.degradation_detection.stub_pipeline import StubRun, stub_run


@pytest.fixture(scope="module")
def run() -> StubRun:
    return stub_run()


def subject_id(run: StubRun, scope: Scope, subject: str) -> str:
    """Series subject of a manifest subject (last-release element id, scenario id or system)."""
    last = run.truth.releases[-1].release_id
    if scope is Scope.ELEMENT:
        [lineage] = [
            lin.lineage_id
            for lin in run.tracking.lineages
            if lin.members[-1].release_id == last and lin.members[-1].element_id == subject
        ]
        return lineage
    if scope is Scope.INSTANCE:
        [planted] = [i for i in run.truth.instances if i.scenario == subject]
        [track] = [
            t.track_id
            for t in run.tracking.tracks
            if t.anti_pattern_type == planted.anti_pattern_type
            and t.occurrences[0].release_id == planted.first_release
        ]
        return track
    return subject


def result(run: StubRun, scope: Scope, subject: str, metric: str) -> TrendResult:
    sid = subject_id(run, scope, subject)
    [found] = [
        r for r in run.analysis.results if (r.scope, r.subject_id, r.metric) == (scope, sid, metric)
    ]
    return found


def test_every_planted_trend_is_significant_and_worsening(run: StubRun) -> None:
    for truth in run.truth.expected_trends:
        r = result(run, truth.scope, truth.subject, truth.metric)
        assert (r.worsening, r.is_worsening, r.is_significant) == (truth.worsening, True, True), (
            truth.scenario,
            truth.metric,
            r.q_value,
        )


def test_no_flat_or_noisy_series_is_significant(run: StubRun) -> None:
    for truth in run.truth.expected_flat:
        r = result(run, truth.scope, truth.subject, truth.metric)
        assert not r.is_significant, (truth.scenario, truth.metric, r.q_value)


def test_untested_series_are_reported_with_their_reason(run: StubRun) -> None:
    reasons = {u.reason for u in run.analysis.untested}
    tested = {(r.scope, r.subject_id, r.metric) for r in run.analysis.results}
    untested = {(u.scope, u.subject_id, u.metric) for u in run.analysis.untested}

    assert reasons <= {SERIES_TOO_SHORT, NO_WORSENING_DIRECTION}
    assert {u.metric for u in run.analysis.untested if u.reason == NO_WORSENING_DIRECTION} == {
        "instability"
    }
    assert tested.isdisjoint(untested)
    assert len(tested) + len(untested) == len(run.tracking.series)


def test_every_expected_event_has_a_candidate(run: StubRun) -> None:
    for expected in run.truth.expected_events:
        matches = [
            c
            for c in run.analysis.candidates
            if c.scope is expected.scope
            and c.anti_pattern_type in expected.anti_pattern_types
            and (expected.element_id is None or c.element_id == expected.element_id)
            and (expected.scope is not Scope.INSTANCE or c.members == expected.members)
        ]
        assert matches, expected.scenario
        if len(expected.anti_pattern_types) == 1:  # S8 accepts BigBallOfMud or MetricDrift
            assert len(matches) == 1, expected.scenario
        if expected.lifecycle is not None:
            assert matches[0].lifecycle is expected.lifecycle, expected.scenario


def test_big_ball_of_mud_is_reported_as_itself_because_it_is_present_at_the_end(
    run: StubRun,
) -> None:
    [mud] = [c for c in run.analysis.candidates if c.anti_pattern_type == "BigBallOfMud"]

    assert {t.metric for t in mud.trends} == {"largest_scc_share", "modularity"}
    assert mud.instance_id == "AP-BigBallOfMud:system@v1.4.0"


def test_non_events_and_unrelated_elements_get_no_candidate(run: StubRun) -> None:
    truth = run.truth
    allowed = {c.element_id for c in truth.collateral} | {
        e.element_id for e in truth.expected_events if e.element_id
    }
    reported = {c.element_id for c in run.analysis.candidates if c.scope is Scope.ELEMENT}

    assert reported <= allowed
    assert reported.isdisjoint({n.element_id for n in truth.expected_non_events})


def test_instance_candidates_are_only_the_planted_instances(run: StubRun) -> None:
    instances = {c.subject_id for c in run.analysis.candidates if c.scope is Scope.INSTANCE}

    assert instances == {subject_id(run, Scope.INSTANCE, i.scenario) for i in run.truth.instances}


def test_downweighted_release_is_listed_in_every_window_that_covers_it(run: StubRun) -> None:
    [low] = [r.release_id for r in run.truth.releases if r.gate_status == "DOWNWEIGHTED"]
    ordinal = {e.release.release_id: e.ordinal for e in run.timeline.entries}

    for c in run.analysis.candidates:
        covers = ordinal[c.start_release] <= ordinal[low] <= ordinal[c.end_release]
        assert (low in c.low_confidence_releases) is covers, c.subject_id


def test_metric_drift_only_where_no_present_anti_pattern_explains_the_trend(
    run: StubRun,
) -> None:
    drift = [c for c in run.analysis.candidates if c.anti_pattern_type == METRIC_DRIFT]

    assert drift, "the stub has uncovered trends (raw fan_in, size, cyclic_edge_count)"
    for c in drift:
        assert c.instance_id is None
        assert c.catalog == "universal"


def test_analysis_is_deterministic(run: StubRun) -> None:
    again = TrendService(run.cfg).analyze(
        run.timeline,
        run.tracking.series,
        run.tracking.lineages,
        run.tracking.tracks,
        run.catalog,
    )

    assert again == run.analysis
