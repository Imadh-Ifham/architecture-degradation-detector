"""Thin M6 (PP1): event candidates -> DegradationEventV2 JSON, validated against the schema."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from app.components.degradation_detection.config import C3Config, ContextConfig
from app.components.degradation_detection.events import EventService
from app.components.degradation_detection.events.emitter import check_against_schema
from app.components.degradation_detection.models import (
    EventCandidate,
    SeriesPoint,
    Timeline,
    TrendResult,
)
from app.domain.canonical_release import GateStatus
from app.domain.degradation_event import (
    ContextStage,
    ContextTag,
    DegradationEventV2,
    Lifecycle,
    ReviewStatus,
    Scope,
    TestMethod,
    TimeAxis,
    Worsening,
)
from app.domain.release_package import ArchitectureStyle
from tests.components.degradation_detection.stub_pipeline import stub_run
from tests.components.degradation_detection.tracking.timelines import rel, timeline

CFG = C3Config()
RUN = "RUN-test"
SCHEMA_FILE = Path(__file__).resolve().parents[4] / "schemas" / "c3_output.schema.json"
BANNED_KEY = ("severity", "priority", "rank", "impact", "blast", "hotspot", "risk")


def release_hash(k: int) -> str:
    return "sha256:" + f"{k:x}" * 64


def tiny_timeline() -> Timeline:
    releases = []
    for k in range(4):
        r = rel(f"v1.{k}.0", ["a", "b"]).model_copy(
            update={
                "package_hash": release_hash(k),
                "c1_model_ref": f"c1-model-{k // 2}",  # one model per two releases
                "c2_validation_ref": None if k == 0 else f"c2-val-{k}",
                "gate_status": GateStatus.DOWNWEIGHTED if k == 2 else GateStatus.ACCEPTED,
            }
        )
        releases.append(r)
    return timeline(*releases)


def trend(metric: str = "member_count", tau: float = 0.8) -> TrendResult:
    return TrendResult(
        scope=Scope.INSTANCE,
        subject_id="AP-CyclicDependency:a@v1.1.0",
        metric=metric,
        unit="count",
        worsening=Worsening.INCREASE,
        points=(
            SeriesPoint(ordinal=1, release_id="v1.1.0", value=2.0),
            SeriesPoint(ordinal=2, release_id="v1.2.0", value=None),
            SeriesPoint(ordinal=3, release_id="v1.3.0", value=3.0),
        ),
        n=2,
        s=1,
        tau=tau,
        p_value=0.004,
        q_value=0.02,
        method=TestMethod.EXACT,
        time_axis=TimeAxis.ORDINAL,
        sen_slope=0.5,
        intercept=1.5,
        is_worsening=True,
        is_significant=True,
    )


def candidate(**overrides: object) -> EventCandidate:
    fields: dict[str, object] = {
        "event_key": "sha256:" + "c" * 64,
        "scope": Scope.INSTANCE,
        "subject_id": "AP-CyclicDependency:a@v1.1.0",
        "anti_pattern_type": "CyclicDependency",
        "catalog": "universal",
        "instance_id": "AP-CyclicDependency:a@v1.1.0",
        "members": ("a", "b"),
        "lifecycle": Lifecycle.GROWING,
        "start_release": "v1.1.0",
        "end_release": "v1.3.0",
        "n_releases": 3,
        "low_confidence_releases": ("v1.2.0",),
        "trends": (trend(),),
        "trend_strength": 0.8,
    }
    return EventCandidate.model_validate(fields | overrides)


def emit_one(c: EventCandidate | None = None, cfg: C3Config = CFG) -> DegradationEventV2:
    [event] = EventService(cfg).emit([c or candidate()], tiny_timeline(), RUN).events
    return event


# --- one event ----------------------------------------------------------------------------


def test_event_carries_the_candidate() -> None:
    event = emit_one()

    assert event.schema_version == "2.0.0"
    assert (event.run_id, event.system_id, event.event_key) == (RUN, "tiny", "sha256:" + "c" * 64)
    assert (event.scope, event.anti_pattern_type, event.catalog) == (
        Scope.INSTANCE,
        "CyclicDependency",
        "universal",
    )
    assert (event.instance_id, event.members, event.lifecycle) == (
        "AP-CyclicDependency:a@v1.1.0",
        ["a", "b"],
        Lifecycle.GROWING,
    )
    assert (event.element_id, event.lineage_id, event.supersedes_event_id) == (None, None, None)
    assert event.architecture_style is ArchitectureStyle.MICROSERVICES
    assert event.window.model_dump() == {
        "start_release": "v1.1.0",
        "end_release": "v1.3.0",
        "n_releases": 3,
        "low_confidence_releases": ["v1.2.0"],
    }
    assert event.trend_strength == 0.8


def test_element_event_names_the_element_and_its_lineage() -> None:
    event = emit_one(
        candidate(
            scope=Scope.ELEMENT,
            subject_id="LIN-a@v1.0.0",
            element_id="a",
            lineage_id="LIN-a@v1.0.0",
            anti_pattern_type="MetricDrift",
            instance_id=None,
            members=(),
            lifecycle=None,
        )
    )

    assert (event.element_id, event.lineage_id, event.instance_id) == ("a", "LIN-a@v1.0.0", None)


def test_context_is_the_trend_only_baseline_and_review_is_pending() -> None:
    event = emit_one()

    assert event.context.model_dump() == {
        "tag": ContextTag.GENUINE,
        "stage": ContextStage.DISABLED,
        "rule_id": "R0_CONTEXT_DISABLED",
        "justification": None,
        "retrieved": [],
        "cited": [],
    }
    assert event.review_status is ReviewStatus.PENDING


def test_context_enabled_is_refused_until_m5_exists() -> None:
    cfg = C3Config(context=ContextConfig(enabled=True))

    with pytest.raises(NotImplementedError, match="M5"):
        emit_one(cfg=cfg)


def test_each_trend_is_an_affected_metric_with_its_series() -> None:
    event = emit_one(candidate(trends=(trend("internal_edge_count", 0.9), trend())))

    assert [m.metric for m in event.affected_metrics] == ["internal_edge_count", "member_count"]
    affected = event.affected_metrics[1].model_dump(mode="json")
    assert affected == {
        "metric": "member_count",
        "unit": "count",
        "worsening": "INCREASE",
        "n": 2,
        "s": 1,
        "tau": 0.8,
        "p_value": 0.004,
        "q_value": 0.02,
        "test_method": "EXACT",
        "sen_slope": 0.5,
        "time_axis": "ordinal",
        "series": [
            {"release_id": "v1.1.0", "value": 2.0},
            {"release_id": "v1.2.0", "value": None},  # null stays null
            {"release_id": "v1.3.0", "value": 3.0},
        ],
    }


def test_provenance_covers_the_releases_of_the_window() -> None:
    event = emit_one()

    assert event.provenance.model_dump() == {
        "release_package_hashes": [release_hash(1), release_hash(2), release_hash(3)],
        "c1_model_refs": ["c1-model-0", "c1-model-1"],  # each once, in release order
        "c2_validation_refs": ["c2-val-1", "c2-val-2", "c2-val-3"],
        "config_hash": CFG.config_hash,
    }


def test_event_id_is_derived_from_run_and_event_key() -> None:
    first = emit_one()
    again = emit_one()
    other_run = EventService(CFG).emit([candidate()], tiny_timeline(), "RUN-other").events[0]
    other_key = emit_one(candidate(event_key="sha256:" + "d" * 64))

    assert first.event_id.startswith("DEG-")
    assert first.event_id == again.event_id
    assert len({first.event_id, other_run.event_id, other_key.event_id}) == 3


# --- the export ---------------------------------------------------------------------------


def test_json_is_the_list_of_events_and_validates_against_the_committed_schema() -> None:
    export = EventService(CFG).emit([candidate()], tiny_timeline(), RUN)
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))

    payload = json.loads(export.text)

    assert payload == [e.model_dump(mode="json") for e in export.events]
    for item in payload:
        jsonschema.validate(item, schema)
    assert export.text.endswith("\n")


def test_no_candidates_export_an_empty_list() -> None:
    export = EventService(CFG).emit([], tiny_timeline(), RUN)

    assert (export.events, export.text) == ((), "[]\n")


def test_schema_check_rejects_a_payload_the_contract_does_not_allow() -> None:
    payload = emit_one().model_dump(mode="json") | {"trend_strength": 2.0}

    with pytest.raises(ValueError, match="DegradationEventV2"):
        check_against_schema([payload])


# --- on the stub --------------------------------------------------------------------------


def keys(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from keys(item)


def test_stub_events_validate_and_carry_no_severity() -> None:
    run = stub_run()

    export = EventService(run.cfg).emit(run.analysis.candidates, run.timeline, RUN)
    payload = json.loads(export.text)
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))

    assert len(payload) == len(run.analysis.candidates) > 0
    for item in payload:
        jsonschema.validate(item, schema)
    assert [k for k in set(keys(payload)) if any(b in k.lower() for b in BANNED_KEY)] == []
    assert len({e.event_key for e in export.events}) == len(export.events)
    downweighted = [e for e in payload if "v1.5.0" in e["window"]["low_confidence_releases"]]
    assert downweighted, "S10: the low-confidence release is listed on the events covering it"
