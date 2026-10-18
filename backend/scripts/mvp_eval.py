"""MVP evaluation (plan T-14, Section 8): one stored analysis run against the stub's ground truth.

Run from ``backend/``, after ``c3 run``:

    uv run python -m scripts.mvp_eval --run-id RUN-...

It writes ``out/<run_id>/mvp_eval.md``. Every number comes from the stored run (events, trend
results, static flags, lineages and tracks) or from a named ground truth:

1. events vs ``expected_events`` / ``expected_non_events`` (rules in ``stub/models.py``);
2. series-level trend outcomes vs ``expected_trends`` / ``expected_flat``;
3. Sen's slope vs the planted slope of the series fixtures, and vs ``scipy.stats.theilslopes``;
4. Mann-Kendall p vs the oracles (scipy exact Kendall, pyMannKendall, full enumeration for the
   permutation method) and BH q vs statsmodels;
5. the detectors on the golden graph fixtures;
6. element links and instance tracks vs the planted ids, rename and instance members;
7. the static-threshold baseline vs C3 on the planted non-events (S3, S6);
8. the planted ingestion scenarios (S10 low-confidence release, S11 rejected package).

The stub is a development fixture: these numbers show that the pipeline finds what was planted,
nothing more. The oracles are dev-only dependencies; this script is a dev tool, never runtime.
"""

import itertools
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Annotated, Any

import numpy as np
import pymannkendall  # type: ignore[import-untyped]
import typer
import yaml
from pydantic import BaseModel, ConfigDict
from scipy import stats
from statsmodels.stats.multitest import multipletests  # type: ignore[import-untyped]

from app.components.degradation_detection.config import C3Config, TrendConfig
from app.components.degradation_detection.detection.registry import ALL_DETECTORS
from app.components.degradation_detection.models import InstanceTrack, Lineage
from app.components.degradation_detection.stub.models import (
    GROUND_TRUTH_FILE,
    ExpectedEvent,
    GroundTruth,
    SeriesFixture,
)
from app.components.degradation_detection.trends.mann_kendall import mann_kendall
from app.components.degradation_detection.trends.sens_slope import sens_slope
from app.core.logging import configure_logging
from app.domain.analysis_run import RunStatus, StaticFlag, StoredRun, TrendRecord, UntestedRecord
from app.domain.canonical_release import GateStatus
from app.domain.degradation_event import DegradationEventV2, Scope, TestMethod
from app.domain.release_package import ReleasePackageV1
from scripts import c3
from tests.components.degradation_detection.detection.graphs import (
    graph_fixtures,
    load_graph_fixture,
)
from tests.components.degradation_detection.detection.universal.run import run as run_detectors

REPORT_FILE = "mvp_eval.md"
# Full enumeration of n! orderings is the permutation oracle; 9! = 362880 is still quick. The
# analyzer uses permutations only below ``exact_below`` (10 by default), so this covers them.
MAX_ENUMERATED = 9
CAVEAT = (
    "The stub is a development fixture, not evidence: these numbers show that the pipeline "
    "finds what was planted in it, nothing more. The configuration was not tuned on this "
    "output (plan T-14, Section 8)."
)

Link = tuple[str, str, str, str]  # (release, element id) -> (next release, element id)


class EvalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def ratio(numerator: int, denominator: int) -> float | None:
    """None when undefined (nothing to divide by), never 0."""
    return numerator / denominator if denominator else None


def f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or precision + recall == 0:
        return None
    return 2 * precision * recall / (precision + recall)


# --- 1. events ------------------------------------------------------------------------------------


class Verdict(StrEnum):
    HIT = "hit"  # the first event matching an expected event
    NEUTRAL = "neutral"  # on collateral or on an expected subject: neither hit nor false alarm
    FALSE_ALARM = "false alarm"  # on a planted non-event or any other element


class ScoredEvent(EvalModel):
    event_id: str
    scope: Scope
    anti_pattern_type: str
    subject: str
    verdict: Verdict
    scenario: str | None = None  # of the expected event it hits
    lifecycle_ok: bool | None = None  # None when the expected event names no lifecycle


class EventScore(EvalModel):
    events: tuple[ScoredEvent, ...]
    hit: tuple[str, ...]  # scenarios
    missed: tuple[str, ...]  # required scenarios not hit
    optional_missed: tuple[str, ...]
    precision: float | None  # hits / (hits + false alarms)
    strict_precision: float | None  # hits / all events (neutral ones count against it)
    recall: float | None  # hits / (required + optional found)
    f1: float | None


def _event_subjects(event: DegradationEventV2) -> frozenset[str]:
    if event.scope is Scope.SYSTEM:
        return frozenset({event.system_id})
    if event.scope is Scope.INSTANCE:
        return frozenset(event.members)
    return frozenset({event.element_id or ""})


def _subject_label(event: DegradationEventV2) -> str:
    if event.scope is Scope.INSTANCE:
        return "{" + ", ".join(sorted(event.members)) + "}"
    return event.system_id if event.scope is Scope.SYSTEM else str(event.element_id)


def _matches(event: DegradationEventV2, expected: ExpectedEvent) -> bool:
    return (
        event.scope is expected.scope
        and event.anti_pattern_type in expected.anti_pattern_types
        and (expected.element_id is None or event.element_id == expected.element_id)
        and (expected.scope is not Scope.INSTANCE or set(event.members) == set(expected.members))
    )


def _allowed_subjects(truth: GroundTruth) -> frozenset[str]:
    """Where an event is not a false alarm: collateral elements and expected subjects."""
    allowed = {c.element_id for c in truth.collateral}
    for x in truth.expected_events:
        allowed.update(x.members)
        if x.element_id is not None:
            allowed.add(x.element_id)
        if x.scope is Scope.SYSTEM:
            allowed.add(truth.system_id)
    return frozenset(allowed)


def score_events(events: Sequence[DegradationEventV2], truth: GroundTruth) -> EventScore:
    allowed = _allowed_subjects(truth)
    hit: set[str] = set()
    scored = []
    for event in events:
        match = next(
            (x for x in truth.expected_events if x.scenario not in hit and _matches(event, x)),
            None,
        )
        if match is not None:
            hit.add(match.scenario)
            lifecycle_ok = None if match.lifecycle is None else event.lifecycle == match.lifecycle
            verdict, scenario = Verdict.HIT, match.scenario
        else:
            lifecycle_ok, scenario = None, None
            verdict = Verdict.NEUTRAL if _event_subjects(event) <= allowed else Verdict.FALSE_ALARM
        scored.append(
            ScoredEvent(
                event_id=event.event_id,
                scope=event.scope,
                anti_pattern_type=event.anti_pattern_type,
                subject=_subject_label(event),
                verdict=verdict,
                scenario=scenario,
                lifecycle_ok=lifecycle_ok,
            )
        )

    required = [x.scenario for x in truth.expected_events if x.required]
    optional_found = [
        x.scenario for x in truth.expected_events if not x.required and x.scenario in hit
    ]
    false_alarms = sum(1 for s in scored if s.verdict is Verdict.FALSE_ALARM)
    precision = ratio(len(hit), len(hit) + false_alarms)
    recall = ratio(len(hit), len(required) + len(optional_found))
    return EventScore(
        events=tuple(scored),
        hit=tuple(sorted(hit)),
        missed=tuple(s for s in required if s not in hit),
        optional_missed=tuple(
            x.scenario for x in truth.expected_events if not x.required and x.scenario not in hit
        ),
        precision=precision,
        strict_precision=ratio(len(hit), len(scored)),
        recall=recall,
        f1=f1(precision, recall),
    )


# --- 2. series-level trends -----------------------------------------------------------------------


class TrendOutcome(StrEnum):
    TP = "TP"  # planted worsening, significant and worsening
    FN = "FN"  # planted worsening, not reported (or not tested, or no series)
    FP = "FP"  # flat by construction, significant
    TN = "TN"  # flat by construction, not significant
    UNTESTED = "untested"  # flat by construction, not tested: excluded, not a true negative


class ScoredTrend(EvalModel):
    scenario: str
    scope: Scope
    subject: str
    metric: str
    expected: str  # "worsening" or "flat"
    outcome: TrendOutcome
    q_value: float | None = None
    note: str | None = None


class TrendScore(EvalModel):
    rows: tuple[ScoredTrend, ...]
    precision: float | None
    recall: float | None
    f1: float | None


def _last_release(truth: GroundTruth) -> str:
    return max(truth.releases, key=lambda r: r.released_at).release_id


def subject_ids(
    truth: GroundTruth, lineages: Sequence[Lineage], tracks: Sequence[InstanceTrack]
) -> dict[tuple[Scope, str], str]:
    """Series subject id of each manifest subject: the lineage of an element of the last release,
    the track of a planted instance (by type and members where it first appears), the system."""
    last = _last_release(truth)
    subjects = {
        (Scope.ELEMENT, lin.members[-1].element_id): lin.lineage_id
        for lin in lineages
        if lin.members[-1].release_id == last
    }
    for planted in truth.instances:
        first = set(planted.members_by_release[planted.first_release])
        found = [
            t.track_id
            for t in tracks
            if t.anti_pattern_type == planted.anti_pattern_type
            and t.occurrences[0].release_id == planted.first_release
            and set(t.occurrences[0].members) == first
        ]
        if len(found) == 1:
            subjects[(Scope.INSTANCE, planted.scenario)] = found[0]
    subjects[(Scope.SYSTEM, truth.system_id)] = truth.system_id
    return subjects


def score_trends(
    truth: GroundTruth,
    trends: Sequence[TrendRecord],
    untested: Sequence[UntestedRecord],
    subjects: Mapping[tuple[Scope, str], str],
) -> TrendScore:
    tested = {(t.scope, t.subject_id, t.metric): t for t in trends}
    skipped = {(u.scope, u.subject_id, u.metric): u for u in untested}
    named = [(t, "worsening") for t in truth.expected_trends] + [
        (f, "flat") for f in truth.expected_flat
    ]
    rows = []
    for item, expected in named:
        sid = subjects.get((item.scope, item.subject))
        key = (item.scope, sid or "", item.metric)
        record, skip = tested.get(key), skipped.get(key)
        note = skip.reason if skip is not None else (None if record else "no series")
        if expected == "worsening":
            ok = (
                record is not None
                and record.is_significant
                and record.is_worsening
                and record.worsening == getattr(item, "worsening", None)
            )
            outcome = TrendOutcome.TP if ok else TrendOutcome.FN
        elif record is None:
            outcome = TrendOutcome.UNTESTED
        else:
            outcome = TrendOutcome.FP if record.is_significant else TrendOutcome.TN
        rows.append(
            ScoredTrend(
                scenario=item.scenario,
                scope=item.scope,
                subject=item.subject,
                metric=item.metric,
                expected=expected,
                outcome=outcome,
                q_value=None if record is None else record.q_value,
                note=note,
            )
        )
    count = Counter(r.outcome for r in rows)
    tp, fp, fn = count[TrendOutcome.TP], count[TrendOutcome.FP], count[TrendOutcome.FN]
    precision, recall = ratio(tp, tp + fp), ratio(tp, tp + fn)
    return TrendScore(
        rows=tuple(rows), precision=precision, recall=recall, f1=f1(precision, recall)
    )


# --- 3. Sen's slope -------------------------------------------------------------------------------


class SlopeCheck(EvalModel):
    name: str
    planted: float
    sen: float
    abs_error: float  # |Sen - planted|: recovery of the truth
    theil: float
    oracle_delta: float  # |Sen - scipy theilslopes|: agreement with the oracle


def _points(fixture: SeriesFixture) -> tuple[list[float], list[float]]:
    pairs = [
        (float(t), v) for t, v in zip(fixture.time, fixture.values, strict=True) if v is not None
    ]
    return [t for t, _ in pairs], [v for _, v in pairs]


def slope_checks(fixtures: Iterable[SeriesFixture]) -> tuple[SlopeCheck, ...]:
    checks = []
    for fixture in fixtures:
        if fixture.planted_slope is None:
            continue
        times, values = _points(fixture)
        sen = sens_slope(times, values).slope
        theil = float(stats.theilslopes(values, times).slope)
        checks.append(
            SlopeCheck(
                name=fixture.name,
                planted=fixture.planted_slope,
                sen=sen,
                abs_error=abs(sen - fixture.planted_slope),
                theil=theil,
                oracle_delta=abs(sen - theil),
            )
        )
    return tuple(checks)


# --- 4. Mann-Kendall and BH against the oracles ---------------------------------------------------


class PCheck(EvalModel):
    label: str
    method: TestMethod
    n: int
    p: float
    oracle_p: float | None  # None: no oracle for this series
    delta: float | None
    mc_se: float | None = None  # Monte Carlo standard error of a permutation p


@cache
def _orderings(n: int) -> np.ndarray[Any, np.dtype[np.int8]]:
    return np.array(list(itertools.permutations(range(n))), dtype=np.int8)


def _s(ranks: np.ndarray[Any, Any]) -> np.ndarray[Any, np.dtype[np.int64]]:
    """Kendall S of each row: concordant minus discordant pairs, ties count 0."""
    n = ranks.shape[-1]
    s = np.zeros(ranks.shape[:-1], dtype=np.int64)
    for i, j in itertools.combinations(range(n), 2):
        s += np.sign(ranks[..., j].astype(np.int64) - ranks[..., i])
    return s


def enumerated_p(values: Sequence[float]) -> float:
    """Exact two-sided p of S under the permutation null: the share of all n! orderings of the
    values (ties included) with |S| at least the observed one."""
    ranks = np.unique(np.asarray(values, dtype=float), return_inverse=True)[1].astype(np.int8)
    observed = abs(int(_s(ranks)))
    every = _s(ranks[_orderings(len(values))])
    return float(np.count_nonzero(np.abs(every) >= observed) / len(every))


def oracle_p(values: Sequence[float], method: TestMethod) -> float | None:
    """The oracle p for the method C3 used; None when there is none: a DEGENERATE (constant)
    series has S = 0 in every ordering and p = 1 by definition, and nothing to compare."""
    if method is TestMethod.DEGENERATE:
        return None
    if method is TestMethod.EXACT:
        p = float(stats.kendalltau(np.arange(len(values)), values, method="exact").pvalue)
    elif method is TestMethod.NORMAL:
        p = float(pymannkendall.original_test(list(values)).p)
    elif len(values) <= MAX_ENUMERATED:
        p = enumerated_p(values)
    else:
        return None
    return None if math.isnan(p) else p


def _check(
    label: str, values: Sequence[float], p: float, method: TestMethod, n_perm: int
) -> PCheck:
    oracle = oracle_p(values, method)
    mc_se = None
    if method is TestMethod.PERMUTATION and oracle is not None:
        mc_se = math.sqrt(oracle * (1 - oracle) / n_perm)
    return PCheck(
        label=label,
        method=method,
        n=len(values),
        p=p,
        oracle_p=oracle,
        delta=None if oracle is None else abs(p - oracle),
        mc_se=mc_se,
    )


def p_checks_for_trends(trends: Iterable[TrendRecord], *, n_perm: int) -> tuple[PCheck, ...]:
    """The p each tested series was reported with, against the oracle on its non-null points."""
    return tuple(
        _check(
            f"{t.scope.value} {t.subject_id} {t.metric}",
            [p.value for p in t.points if p.value is not None],
            t.p_value,
            t.method,
            n_perm,
        )
        for t in trends
    )


def p_checks_for_fixtures(
    fixtures: Iterable[SeriesFixture], trend: TrendConfig
) -> tuple[PCheck, ...]:
    checks = []
    for fixture in fixtures:
        values = _points(fixture)[1]
        result = mann_kendall(
            values, exact_below=trend.exact_below, n_perm=trend.n_perm, seed=trend.seed
        )
        checks.append(_check(fixture.name, values, result.p_value, result.method, trend.n_perm))
    return tuple(checks)


def q_max_delta(trends: Sequence[TrendRecord]) -> float | None:
    """Largest |q - statsmodels BH q| over the run's BH family (every tested series)."""
    if not trends:
        return None
    oracle = multipletests([t.p_value for t in trends], method="fdr_bh")[1]
    return max(abs(t.q_value - float(q)) for t, q in zip(trends, oracle, strict=True))


# --- 5. golden fixtures ---------------------------------------------------------------------------


class FixtureCheck(EvalModel):
    name: str
    passed: bool  # exactly the expected instances, with the expected measures
    expected: int
    found: int


class DetectorCount(EvalModel):
    detector: str
    tp: int
    fp: int
    fn: int


class GoldenScore(EvalModel):
    fixtures: tuple[FixtureCheck, ...]
    detectors: tuple[DetectorCount, ...]


InstanceKey = tuple[str, str, tuple[str, ...]]


def _same_measures(got: Mapping[str, float | None], want: Mapping[str, Any]) -> bool:
    if set(got) != set(want):
        return False
    for name, value in got.items():
        other = want[name]
        if (value is None) != (other is None):
            return False
        if value is not None and not math.isclose(value, other, rel_tol=1e-9, abs_tol=1e-12):
            return False
    return True


def golden_checks(paths: Iterable[Path]) -> GoldenScore:
    fixtures = []
    counts = {d.id: Counter[str]() for d in ALL_DETECTORS}
    for path in paths:
        release, expected = load_graph_fixture(path)
        found = run_detectors(release, ALL_DETECTORS)
        got = {(i.anti_pattern_type, i.scope.value, i.members): i.measures for i in found}
        want = {
            (e["anti_pattern_type"], e["scope"], tuple(e["members"])): e["measures"]
            for e in expected
        }
        for key in got.keys() | want.keys():
            outcome = "tp" if key in got and key in want else ("fp" if key in got else "fn")
            counts.setdefault(key[0], Counter())[outcome] += 1
        passed = got.keys() == want.keys() and all(_same_measures(got[k], want[k]) for k in got)
        fixtures.append(
            FixtureCheck(name=path.stem, passed=passed, expected=len(want), found=len(got))
        )
    return GoldenScore(
        fixtures=tuple(fixtures),
        detectors=tuple(
            DetectorCount(detector=d, tp=c["tp"], fp=c["fp"], fn=c["fn"])
            for d, c in sorted(counts.items())
        ),
    )


# --- 6. identity: element links and instance tracks -----------------------------------------------


class LinkScore(EvalModel):
    truth: int
    predicted: int
    correct: int
    wrong: int  # predicted links that are not planted
    renames: int
    renames_correct: int
    precision: float | None
    recall: float | None


class InstanceCheck(EvalModel):
    scenario: str
    anti_pattern_type: str
    occurrences: int  # releases the planted instance exists in
    occurrences_correct: int  # found there with exactly the planted members
    links: int  # consecutive pairs of those releases
    links_kept: int  # both ends in one track, with the planted members
    one_track: bool  # a single track is exactly the planted instance


def _release_order(truth: GroundTruth) -> list[str]:
    return [r.release_id for r in sorted(truth.releases, key=lambda r: r.released_at)]


def element_ids(truth: GroundTruth, truth_dir: Path) -> dict[str, frozenset[str]]:
    """Element ids in each main-line release, read from the input packages beside the truth."""
    ids = {}
    for r in truth.releases:
        package = ReleasePackageV1.model_validate_json((truth_dir / r.file).read_bytes())
        ids[r.release_id] = frozenset(e.id for e in package.elements)
    return ids


def truth_links(truth: GroundTruth, ids: Mapping[str, frozenset[str]]) -> frozenset[Link]:
    """Planted identity between consecutive releases: the same id, or a planted rename."""
    links = set()
    for a, b in itertools.pairwise(_release_order(truth)):
        renamed = {x.from_id: x.to_id for x in truth.renames if x.at_release == b}
        for element in ids[a]:
            target = renamed.get(element, element)
            if target in ids[b]:
                links.add((a, element, b, target))
    return frozenset(links)


def lineage_links(lineages: Iterable[Lineage]) -> frozenset[Link]:
    return frozenset(
        (m.release_id, m.element_id, n.release_id, n.element_id)
        for lin in lineages
        for m, n in itertools.pairwise(lin.members)
    )


def score_links(
    truth: GroundTruth, planted: frozenset[Link] | set[Link], predicted: frozenset[Link] | set[Link]
) -> LinkScore:
    renames = {link for link in planted if link[1] != link[3]}
    correct = len(planted & predicted)
    return LinkScore(
        truth=len(planted),
        predicted=len(predicted),
        correct=correct,
        wrong=len(predicted - planted),
        renames=len(renames),
        renames_correct=len(renames & predicted),
        precision=ratio(correct, len(predicted)),
        recall=ratio(correct, len(planted)),
    )


def instance_checks(
    truth: GroundTruth, tracks: Sequence[InstanceTrack]
) -> tuple[InstanceCheck, ...]:
    order = _release_order(truth)
    checks = []
    for planted in truth.instances:
        want = {r: frozenset(m) for r, m in planted.members_by_release.items()}
        releases = [r for r in order if r in want]
        seen = [
            {o.release_id: frozenset(o.members) for o in t.occurrences}
            for t in tracks
            if t.anti_pattern_type == planted.anti_pattern_type
        ]
        checks.append(
            InstanceCheck(
                scenario=planted.scenario,
                anti_pattern_type=planted.anti_pattern_type,
                occurrences=len(releases),
                occurrences_correct=sum(
                    1 for r in releases if any(s.get(r) == want[r] for s in seen)
                ),
                links=len(releases) - 1,
                links_kept=sum(
                    1
                    for a, b in itertools.pairwise(releases)
                    if any(s.get(a) == want[a] and s.get(b) == want[b] for s in seen)
                ),
                one_track=any(s == want for s in seen),
            )
        )
    return tuple(checks)


# --- 7. static baseline ---------------------------------------------------------------------------


class StaticRow(EvalModel):
    element_id: str
    metric: str
    value: float
    threshold: float
    c3_events: int
    planted: str


class NonEventRow(EvalModel):
    scenario: str
    element_id: str
    static_rule: str  # what the manifest says a fixed threshold flags
    flagged: bool  # the run's static baseline flagged it
    c3_events: int


class StaticScore(EvalModel):
    rows: tuple[StaticRow, ...]
    non_events: tuple[NonEventRow, ...]
    avoided: int  # planted non-events the baseline flags and C3 does not report


def _events_on(element_id: str, events: Iterable[DegradationEventV2]) -> int:
    return sum(
        1
        for e in events
        if (e.scope is Scope.ELEMENT and e.element_id == element_id)
        or (e.scope is Scope.INSTANCE and element_id in e.members)
    )


def _planted_role(element_id: str, truth: GroundTruth) -> str:
    for n in truth.expected_non_events:
        if n.element_id == element_id:
            return f"non-event ({n.scenario})"
    for x in truth.expected_events:
        if x.element_id == element_id:
            return f"expected event ({x.scenario})"
    for c in truth.collateral:
        if c.element_id == element_id:
            return f"collateral ({c.scenario})"
    return "not planted"


def static_comparison(
    flags: Sequence[StaticFlag], events: Sequence[DegradationEventV2], truth: GroundTruth
) -> StaticScore:
    flagged = {f.element_id for f in flags}
    non_events = tuple(
        NonEventRow(
            scenario=n.scenario,
            element_id=n.element_id,
            static_rule=n.static_flag,
            flagged=n.element_id in flagged,
            c3_events=_events_on(n.element_id, events),
        )
        for n in truth.expected_non_events
    )
    return StaticScore(
        rows=tuple(
            StaticRow(
                element_id=f.element_id,
                metric=f.metric,
                value=f.value,
                threshold=f.threshold,
                c3_events=_events_on(f.element_id, events),
                planted=_planted_role(f.element_id, truth),
            )
            for f in flags
        ),
        non_events=non_events,
        avoided=sum(1 for n in non_events if n.flagged and n.c3_events == 0),
    )


# --- 8. ingestion scenarios -----------------------------------------------------------------------


def low_confidence_check(
    events: Iterable[DegradationEventV2], truth: GroundTruth, releases: Sequence[str]
) -> tuple[int, int]:
    """(events whose window covers a DOWNWEIGHTED release, of those the ones that list it)."""
    low = {r.release_id for r in truth.releases if r.gate_status is GateStatus.DOWNWEIGHTED}
    index = {r: i for i, r in enumerate(releases)}
    covering = listed = 0
    for event in events:
        start, end = index.get(event.window.start_release), index.get(event.window.end_release)
        if start is None or end is None:
            continue
        inside = {r for r in low if r in index and start <= index[r] <= end}
        if inside:
            covering += 1
            listed += inside <= set(event.window.low_confidence_releases)
    return covering, listed


# --- the evaluation -------------------------------------------------------------------------------


class Evaluation(EvalModel):
    stored: StoredRun
    truth_seed: int
    truth_schema: str
    min_releases: int
    n_perm: int
    events: EventScore
    trends: TrendScore
    slopes: tuple[SlopeCheck, ...]
    p_trends: tuple[PCheck, ...]
    p_fixtures: tuple[PCheck, ...]
    q_delta: float | None
    golden: GoldenScore
    links: LinkScore
    instances: tuple[InstanceCheck, ...]
    static: StaticScore
    low_confidence: tuple[int, int]
    rejected_absent: bool


def evaluate(
    stored: StoredRun,
    artifacts: Mapping[str, Any],
    truth: GroundTruth,
    truth_dir: Path,
    series_fixtures: Sequence[SeriesFixture],
    golden_paths: Iterable[Path],
) -> Evaluation:
    """Score a COMPLETED run. Raises ``ValueError`` if it is not one, or if the ground truth is
    for another system or another timeline."""
    run = stored.run
    if run.status is not RunStatus.COMPLETED:
        raise ValueError(f"run {run.run_id} is {run.status.value}, not COMPLETED")
    if truth.system_id != run.system_id:
        raise ValueError(
            f"ground truth is for system {truth.system_id!r}, "
            f"run {run.run_id} for {run.system_id!r}"
        )
    releases = [r.release_id for r in run.releases]
    if releases != _release_order(truth):
        raise ValueError(f"run timeline {releases} is not the ground-truth timeline")

    cfg = C3Config.model_validate(run.config)
    lineages = [Lineage.model_validate(x) for x in artifacts["lineages"]]
    tracks = [InstanceTrack.model_validate(x) for x in artifacts["tracks"]]
    out = stored.outputs
    return Evaluation(
        stored=stored,
        truth_seed=truth.seed,
        truth_schema=truth.schema_version,
        min_releases=cfg.trend.min_releases,
        n_perm=cfg.trend.n_perm,
        events=score_events(out.events, truth),
        trends=score_trends(truth, out.trends, out.untested, subject_ids(truth, lineages, tracks)),
        slopes=slope_checks(series_fixtures),
        p_trends=p_checks_for_trends(out.trends, n_perm=cfg.trend.n_perm),
        p_fixtures=p_checks_for_fixtures(series_fixtures, cfg.trend),
        q_delta=q_max_delta(out.trends),
        golden=golden_checks(golden_paths),
        links=score_links(
            truth, truth_links(truth, element_ids(truth, truth_dir)), lineage_links(lineages)
        ),
        instances=instance_checks(truth, tracks),
        static=static_comparison(out.static_flags, out.events, truth),
        low_confidence=low_confidence_check(out.events, truth, releases),
        rejected_absent=all(r.release_id not in releases for r in truth.rejected),
    )


# --- the report -----------------------------------------------------------------------------------

ORACLE_NAMES = {
    TestMethod.EXACT: "scipy.stats.kendalltau(method='exact')",
    TestMethod.NORMAL: "pymannkendall.original_test",
    TestMethod.PERMUTATION: f"full enumeration of n! orderings (n <= {MAX_ENUMERATED})",
    TestMethod.DEGENERATE: "none: constant series, p = 1 by definition",
}
# A Monte Carlo p within this many standard errors of the enumerated p counts as agreeing.
MC_SE_TOLERANCE = 4


def _r(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _e(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1e}"


def _g(value: float | None) -> str:
    return "n/a" if value is None else f"{value + 0.0:.6g}"  # + 0.0: no "-0"


def _yes(value: bool | None) -> str:
    return "" if value is None else ("yes" if value else "no")


def _frac(numerator: int, denominator: int) -> str:
    return f"{_r(ratio(numerator, denominator))} ({numerator}/{denominator})"


def _max(values: Iterable[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return max(present) if present else None


def _table(header: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return [*lines, ""]


def _permutation_checks(ev: Evaluation) -> list[PCheck]:
    return [c for c in (*ev.p_trends, *ev.p_fixtures) if c.method is TestMethod.PERMUTATION]


def _within_mc_error(check: PCheck) -> bool:
    return (
        check.delta is not None
        and check.mc_se is not None
        and check.delta <= MC_SE_TOLERANCE * check.mc_se
    )


def _header(ev: Evaluation) -> list[str]:
    run, out = ev.stored.run, ev.stored.outputs
    first, last = run.releases[0].release_id, run.releases[-1].release_id
    libraries = ", ".join(f"{k} {v}" for k, v in sorted(run.lib_versions.items()))
    rows = [
        ["Run", f"`{run.run_id}` ({run.status.value})"],
        ["System", f"{run.system_id}, {len(run.releases)} releases ({first} to {last})"],
        ["Config hash", f"`{run.config_hash}`"],
        ["Code version", f"`{run.code_version}`"],
        ["Libraries", libraries],
        ["Ground truth", f"stub seed {ev.truth_seed}, manifest schema {ev.truth_schema}"],
        [
            "Series",
            f"{len(out.trends)} tested, {len(out.untested)} not tested "
            f"(minimum {ev.min_releases} non-null releases)",
        ],
        ["Events", str(len(out.events))],
    ]
    return [f"# MVP evaluation: run {run.run_id}", "", f"> {CAVEAT}", "", *_table(["", ""], rows)]


def _summary_table(ev: Evaluation) -> list[str]:
    e, verdicts = ev.events, Counter(s.verdict for s in ev.events.events)
    hits, false_alarms = len(e.hit), verdicts[Verdict.FALSE_ALARM]
    outcomes = Counter(r.outcome for r in ev.trends.rows)
    tp, fp, fn = (outcomes[o] for o in (TrendOutcome.TP, TrendOutcome.FP, TrendOutcome.FN))
    exact_or_normal = _max(
        c.delta
        for c in (*ev.p_trends, *ev.p_fixtures)
        if c.method in (TestMethod.EXACT, TestMethod.NORMAL)
    )
    perm = _permutation_checks(ev)
    within = sum(1 for c in perm if _within_mc_error(c))
    golden = ev.golden.fixtures
    passed = sum(f.passed for f in golden)
    links = ev.links
    kept = sum(c.links_kept for c in ev.instances)
    instance_links = sum(c.links for c in ev.instances)
    slope_error = _max(s.abs_error for s in ev.slopes)
    avoided = f"{ev.static.avoided}/{len(ev.static.non_events)}"
    recall, precision = _frac(hits, hits + len(e.missed)), _frac(hits, hits + false_alarms)
    link_recall = _frac(links.correct, links.truth)
    link_precision = _frac(links.correct, links.predicted)
    within_se = f"permutation p within {MC_SE_TOLERANCE} SE"
    rows = [
        ["Planted worsening is reported", "expected events", "recall", recall],
        ["", "expected events, non-events", "precision", precision],
        ["", "", "strict precision (neutral counted)", _frac(hits, len(e.events))],
        ["", "", "F1", _r(e.f1)],
        ["Worsening series are significant", "expected trends", "recall", _frac(tp, tp + fn)],
        ["Flat series are not", "expected flat series", "precision", _frac(tp, tp + fp)],
        ["Sen's slope recovers the slope", "series fixtures", "max abs error", _e(slope_error)],
        ["Mann-Kendall p is correct", "oracles", "max abs p diff", _e(exact_or_normal)],
        ["", "full enumeration", within_se, f"{within}/{len(perm)}"],
        ["BH q is correct", "statsmodels fdr_bh", "max abs q difference", _e(ev.q_delta)],
        ["Detectors are exact", "golden graph fixtures", "pass rate", _frac(passed, len(golden))],
        ["Element identity is kept", "planted ids, rename", "link recall", link_recall],
        ["", "", "link precision", link_precision],
        ["Instance identity is kept", "planted members", "links kept", _frac(kept, instance_links)],
        ["Trends beat static thresholds", "non-events S3, S6", "baseline FPs avoided", avoided],
    ]  # fmt: skip
    return ["## Summary", "", *_table(["Claim", "Ground truth", "Metric", "Result"], rows)]


def _events_section(e: EventScore) -> list[str]:
    rows = [
        [f"`{s.event_id}`", s.scope.value, s.anti_pattern_type, s.subject, s.verdict.value,
         s.scenario or "", _yes(s.lifecycle_ok)]
        for s in e.events
    ]  # fmt: skip
    header = ["Event", "Scope", "Type", "Subject", "Verdict", "Scenario", "Lifecycle as planted"]
    return [
        "## 1. Events against the ground truth",
        "",
        "Each event is matched, in export order, to the first expected event with the same scope,",
        "an accepted type, the same element (ELEMENT) and the same members (INSTANCE); a later",
        "event on a scenario already hit does not hit it again. An unmatched event is *neutral*",
        "when every subject is a collateral element or the subject of an expected event, and a",
        "*false alarm* otherwise (`stub/models.py`). Precision leaves neutral events out; strict",
        "precision counts them as false alarms. Recall counts every required scenario and the",
        "optional ones that were found.",
        "",
        *_table(header, rows),
        f"Hit: {', '.join(e.hit) or 'none'}. Missed (required): {', '.join(e.missed) or 'none'}. "
        f"Missed (optional): {', '.join(e.optional_missed) or 'none'}.",
        "",
    ]


def _trends_section(t: TrendScore) -> list[str]:
    rows = [
        [r.scenario, r.scope.value, r.subject, r.metric, r.expected, r.outcome.value,
         _g(r.q_value), r.note or ""]
        for r in t.rows
    ]  # fmt: skip
    header = ["Scenario", "Scope", "Subject", "Metric", "Planted", "Outcome", "q", "Note"]
    return [
        "## 2. Planted trends, series by series",
        "",
        "A planted worsening series is a TP when it is significant (BH q) and worsening in the",
        "planted direction. A flat series that was not tested is excluded, not a true negative.",
        "",
        *_table(header, rows),
    ]


def _slopes_section(slopes: Sequence[SlopeCheck]) -> list[str]:
    rows = [
        [s.name, _g(s.planted), _g(s.sen), _e(s.abs_error), _g(s.theil), _e(s.oracle_delta)]
        for s in slopes
    ]
    header = ["Fixture", "Planted", "Sen", "Abs error", "scipy theilslopes", "Abs difference"]
    return ["## 3. Sen's slope on planted-slope series", "", *_table(header, rows)]


def _method_rows(checks: Sequence[PCheck]) -> list[list[object]]:
    rows: list[list[object]] = []
    for method in TestMethod:
        group = [c for c in checks if c.method is method]
        if group:
            compared = sum(1 for c in group if c.delta is not None)
            biggest = _e(_max(c.delta for c in group))
            rows.append([method.value, len(group), compared, biggest, ORACLE_NAMES[method]])
    return rows


def _oracle_section(ev: Evaluation) -> list[str]:
    header = ["Method", "Series", "With oracle", "Max abs p difference", "Oracle"]
    perm_rows = [
        [c.label, c.n, _g(c.p), _g(c.oracle_p), _e(c.delta), _e(c.mc_se)]
        for c in _permutation_checks(ev)
    ]
    perm_header = ["Series", "n", "C3 p", "Enumerated p", "Abs difference", "Monte Carlo SE"]
    return [
        "## 4. Mann-Kendall and Benjamini-Hochberg against the oracles",
        "",
        "Every series the run tested (with the p it was reported with) and every series fixture,",
        "each against the oracle for the method C3 chose. A permutation p is a Monte Carlo",
        f"estimate ({ev.n_perm} shuffles), so its difference from the enumerated p is sampling",
        "error; it is shown with its standard error.",
        "",
        "Run series:",
        "",
        *_table(header, _method_rows(ev.p_trends)),
        "Series fixtures:",
        "",
        *_table(header, _method_rows(ev.p_fixtures)),
        "Permutation p-values:",
        "",
        *_table(perm_header, perm_rows),
        f"BH over the run's family of {len(ev.stored.outputs.trends)} tested series: max abs q "
        f"difference from statsmodels `fdr_bh` {_e(ev.q_delta)}.",
        "",
    ]


def _golden_section(golden: GoldenScore) -> list[str]:
    fixtures = [[f.name, f.expected, f.found, _yes(f.passed)] for f in golden.fixtures]
    detectors = [
        [d.detector, d.tp, d.fp, d.fn, _r(ratio(d.tp, d.tp + d.fp)), _r(ratio(d.tp, d.tp + d.fn))]
        for d in golden.detectors
    ]
    return [
        "## 5. Detectors on the golden graph fixtures",
        "",
        *_table(["Fixture", "Expected instances", "Found", "Pass"], fixtures),
        *_table(["Detector", "TP", "FP", "FN", "Precision", "Recall"], detectors),
    ]


def _identity_section(links: LinkScore, instances: Sequence[InstanceCheck]) -> list[str]:
    link_header = [
        "Planted",
        "Predicted",
        "Correct",
        "Wrong",
        "Renames linked",
        "Precision",
        "Recall",
    ]
    link_row = [
        links.truth, links.predicted, links.correct, links.wrong,
        f"{links.renames_correct}/{links.renames}", _r(links.precision), _r(links.recall),
    ]  # fmt: skip
    instance_rows = [
        [c.scenario, c.anti_pattern_type, f"{c.occurrences_correct}/{c.occurrences}",
         f"{c.links_kept}/{c.links}", _yes(c.one_track)]
        for c in instances
    ]  # fmt: skip
    instance_header = ["Scenario", "Type", "Planted members found", "Links kept", "One track"]
    return [
        "## 6. Identity across releases",
        "",
        "Element links: (release, id) to (next release, id) for every element kept or renamed,",
        "from the input packages and the planted renames; predicted links are consecutive",
        "lineage members. Instance links: consecutive releases of a planted instance found in",
        "one track with exactly the planted members.",
        "",
        *_table(link_header, [link_row]),
        *_table(instance_header, instance_rows),
    ]


def _static_section(static: StaticScore, last_release: str) -> list[str]:
    flags = [
        [r.element_id, f"{r.metric} > {_g(r.threshold)}", _g(r.value), r.c3_events, r.planted]
        for r in static.rows
    ]
    non_events = [
        [n.scenario, n.element_id, n.static_rule, _yes(n.flagged), n.c3_events]
        for n in static.non_events
    ]
    return [
        "## 7. Static-threshold baseline vs C3",
        "",
        f"What the run's static baseline flags at {last_release}, and how many C3 events name",
        "the element.",
        "",
        *_table(["Element", "Rule", "Value", "C3 events", "Planted as"], flags),
        *_table(["Scenario", "Element", "Manifest rule", "Flagged", "C3 events"], non_events),
    ]


def _ingestion_section(ev: Evaluation) -> list[str]:
    covering, listed = ev.low_confidence
    rejected = "are not" if ev.rejected_absent else "ARE"
    return [
        "## 8. Ingestion scenarios",
        "",
        f"- S10: {listed}/{covering} events whose window covers a DOWNWEIGHTED release list it "
        "as low-confidence.",
        f"- S11: rejected packages {rejected} on the run's timeline.",
        "",
        "## Not evaluated here",
        "",
        "Real systems, agreement with Arcan/Designite, controlled graph mutation, the RAG",
        "context layer and architect review are later evaluations (plan Section 8).",
        "",
    ]


def _summary(ev: Evaluation) -> str:
    """One line for the terminal."""
    verdicts = Counter(s.verdict for s in ev.events.events)
    golden = ev.golden.fixtures
    return (
        f"events: {len(ev.events.hit)} hits, {len(ev.events.missed)} missed, "
        f"{verdicts[Verdict.FALSE_ALARM]} false alarms, {verdicts[Verdict.NEUTRAL]} neutral; "
        f"golden fixtures {sum(f.passed for f in golden)}/{len(golden)}; "
        f"lineage links {ev.links.correct}/{ev.links.truth}; "
        f"static false positives avoided {ev.static.avoided}"
    )


def render(ev: Evaluation) -> str:
    sections = [
        _header(ev),
        _summary_table(ev),
        _events_section(ev.events),
        _trends_section(ev.trends),
        _slopes_section(ev.slopes),
        _oracle_section(ev),
        _golden_section(ev.golden),
        _identity_section(ev.links, ev.instances),
        _static_section(ev.static, ev.stored.run.releases[-1].release_id),
        _ingestion_section(ev),
    ]
    return "\n".join(line for section in sections for line in section)


# --- command line ---------------------------------------------------------------------------------

app = typer.Typer(
    help="Score a stored analysis run against the stub's ground truth.", add_completion=False
)


def _series_fixtures(directory: Path) -> list[SeriesFixture]:
    return [
        SeriesFixture.model_validate_json(p.read_bytes()) for p in sorted(directory.glob("*.json"))
    ]


@app.command()
def main(
    run_id: Annotated[str, typer.Option("--run-id", help="A stored analysis run.")],
    truth: Annotated[
        Path, typer.Option(help="ground_truth.yaml; the release packages must be beside it.")
    ] = c3.STUB_SYSTEM_DIR / GROUND_TRUTH_FILE,
    series_dir: Annotated[
        Path, typer.Option(help="Series fixtures with planted slopes.")
    ] = c3.SERIES_FIXTURE_DIR,
) -> None:
    """Write out/<run_id>/mvp_eval.md."""
    configure_logging("WARNING")
    if not truth.is_file():
        typer.echo(f"no ground truth at {truth}; run `c3 stub generate` first")
        raise typer.Exit(code=1)
    runs = c3.run_repository()
    stored, artifacts = runs.load(run_id), runs.load_artifacts(run_id)
    if stored is None or artifacts is None:
        typer.echo(f"no analysis run {run_id!r}")
        raise typer.Exit(code=1)
    ground = GroundTruth.model_validate(yaml.safe_load(truth.read_text(encoding="utf-8")))
    try:
        ev = evaluate(
            stored, artifacts, ground, truth.parent, _series_fixtures(series_dir), graph_fixtures()
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    path = c3.OUT_DIR / run_id / REPORT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(ev), encoding="utf-8", newline="\n")
    typer.echo(_summary(ev))
    typer.echo(f"wrote {path}")


if __name__ == "__main__":
    app()
