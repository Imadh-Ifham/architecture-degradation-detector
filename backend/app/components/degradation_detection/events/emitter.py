"""Event candidate -> ``DegradationEventV2``, and the schema check of the export.

- ``event_id`` = ``DEG-`` + the start of ``sha256(run_id, event_key)``: unique per run and
  event, and the same when a run is replayed, so a re-run gives byte-identical output.
- ``architecture_style`` is copied from the window's last release (pass-through: nothing here
  acts on it, ``test_style_agnostic.py`` allows this module to read it).
- Provenance lists the package hash of every release in the window and each C1 / C2 reference
  once, in release order, plus the run's ``config_hash``.
- The payload is checked against the JSON Schema generated from the contract model, the same
  schema ``c3 schemas export`` writes to ``schemas/c3_output.schema.json`` (a snapshot test keeps
  the two equal), so C4 never receives an event its schema rejects.
"""

import json
from collections.abc import Iterable, Sequence
from functools import cache
from typing import Any

import jsonschema

from app.components.degradation_detection.models import EventCandidate, Timeline, TrendResult
from app.domain.canonical_release import CanonicalRelease
from app.domain.degradation_event import (
    AffectedMetric,
    Context,
    ContextStage,
    ContextTag,
    DegradationEventV2,
    EventProvenance,
    SeriesValue,
    Window,
)
from app.shared.canonical_json import content_hash

# Plan M5 stage-1 rule: context disabled -> GENUINE, the trend-only ablation baseline [D-28].
CONTEXT_DISABLED_RULE = "R0_CONTEXT_DISABLED"
EVENT_ID_HEX = 26  # 104 bits: no collision among the events of any realistic number of runs


def to_event(
    candidate: EventCandidate, timeline: Timeline, *, run_id: str, config_hash: str
) -> DegradationEventV2:
    window = _window_releases(candidate, timeline)
    return DegradationEventV2(
        event_id=event_id(run_id, candidate.event_key),
        event_key=candidate.event_key,
        run_id=run_id,
        system_id=timeline.system_id,
        scope=candidate.scope,
        anti_pattern_type=candidate.anti_pattern_type,
        catalog=candidate.catalog,
        architecture_style=window[-1].architecture_style,
        instance_id=candidate.instance_id,
        members=list(candidate.members),
        element_id=candidate.element_id,
        lineage_id=candidate.lineage_id,
        lifecycle=candidate.lifecycle,
        window=Window(
            start_release=candidate.start_release,
            end_release=candidate.end_release,
            n_releases=candidate.n_releases,
            low_confidence_releases=list(candidate.low_confidence_releases),
        ),
        affected_metrics=[_affected(t) for t in candidate.trends],
        trend_strength=candidate.trend_strength,
        context=Context(
            tag=ContextTag.GENUINE, stage=ContextStage.DISABLED, rule_id=CONTEXT_DISABLED_RULE
        ),
        provenance=EventProvenance(
            c1_model_refs=_once(r.c1_model_ref for r in window),
            c2_validation_refs=_once(r.c2_validation_ref for r in window),
            release_package_hashes=[r.package_hash for r in window],
            config_hash=config_hash,
        ),
    )


def event_id(run_id: str, event_key: str) -> str:
    digest = content_hash({"run_id": run_id, "event_key": event_key}).removeprefix("sha256:")
    return f"DEG-{digest[:EVENT_ID_HEX]}"


def check_against_schema(payload: Sequence[dict[str, Any]]) -> None:
    validator = _validator()
    for item in payload:
        errors = sorted(validator.iter_errors(item), key=lambda e: list(e.absolute_path))
        if errors:
            where = "/".join(str(p) for p in errors[0].absolute_path) or "<root>"
            raise ValueError(f"event violates DegradationEventV2 at {where}: {errors[0].message}")


def events_json(payload: Sequence[dict[str, Any]]) -> str:
    return json.dumps(list(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


@cache
def _validator() -> jsonschema.protocols.Validator:
    schema = DegradationEventV2.model_json_schema()
    validator_class = jsonschema.validators.validator_for(schema)
    validator_class.check_schema(schema)
    return validator_class(schema)


def _affected(trend: TrendResult) -> AffectedMetric:
    return AffectedMetric(
        metric=trend.metric,
        unit=trend.unit,
        worsening=trend.worsening,
        n=trend.n,
        s=trend.s,
        tau=trend.tau,
        p_value=trend.p_value,
        q_value=trend.q_value,
        test_method=trend.method,
        sen_slope=trend.sen_slope,
        time_axis=trend.time_axis,
        series=[SeriesValue(release_id=p.release_id, value=p.value) for p in trend.points],
    )


def _window_releases(candidate: EventCandidate, timeline: Timeline) -> list[CanonicalRelease]:
    ids = [entry.release.release_id for entry in timeline.entries]
    start, end = ids.index(candidate.start_release), ids.index(candidate.end_release)
    return [entry.release for entry in timeline.entries[start : end + 1]]


def _once(refs: Iterable[str | None]) -> list[str]:
    return list(dict.fromkeys(ref for ref in refs if ref is not None))
