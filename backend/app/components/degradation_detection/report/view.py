"""A stored run, as one document a screen can draw (pure).

``report.md`` is the run for a person reading a file; this is the same run for a screen: one
JSON-ready mapping with every release's graph, the anti-patterns found in it, the series M4
tested (and the ones it did not, with the reason) and the events handed to C4.

Everything is read from what the run stored - its outputs and its JSON artifacts - plus the
stored releases for the graphs themselves. Nothing is recomputed: a second computation of a
number is a second implementation of it, and the two would disagree on the run somebody is
looking at.

Releases that are stored but not on the run's timeline are listed too, with the reason, so a
release that was gated out or is off the main line is visible rather than missing.
"""

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from app.domain.analysis_run import StoredRun
from app.domain.canonical_release import CanonicalRelease, GateStatus

OFF_MAIN_LINE = "not on the main release line"
EXCLUDED = "validation confidence below the exclusion threshold"
NOT_IN_RUN = "stored after this run"


def run_view(
    stored: StoredRun,
    artifacts: Mapping[str, Any],
    releases: Sequence[CanonicalRelease],
) -> dict[str, Any]:
    """The run, its releases and everything it found, as one JSON-ready mapping."""
    run = stored.run
    outputs = stored.outputs
    config = run.config
    on_timeline = {release.release_id: release.ordinal for release in run.releases}

    detections = {d["release_id"]: d for d in artifacts.get("detections", [])}
    lineage_of = _lineage_index(artifacts.get("lineages", []))
    track_of = _track_index(artifacts.get("tracks", []))
    instances: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for instance in outputs.instances:
        track = track_of.get((instance.release_id, instance.local_instance_id), {})
        instances[instance.release_id].append(
            instance.model_dump(mode="json")
            | {"track_id": track.get("track_id"), "transition": track.get("transition")}
        )

    main_line = re.compile(str(config.get("ingest", {}).get("release_line_regex", "")))
    by_id = {release.release_id: release for release in releases}
    ordered = [by_id[r.release_id] for r in run.releases if r.release_id in by_id]
    ordered += sorted(
        (release for release in releases if release.release_id not in on_timeline),
        key=lambda release: (release.released_at, release.release_id),
    )

    return {
        "run": {
            "run_id": run.run_id,
            "system_id": run.system_id,
            "status": run.status.value,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "config_hash": run.config_hash,
            "code_version": run.code_version,
            "timings": run.timings,
            "error": run.error,
            "trend": config.get("trend", {}),
            "gate": config.get("gate", {}),
        },
        "releases": [
            _release(
                release,
                on_timeline.get(release.release_id),
                _absence(release, on_timeline, main_line),
                detections.get(release.release_id),
                instances.get(release.release_id, []),
                lineage_of,
            )
            for release in ordered
        ],
        "lineages": [
            {
                "lineage_id": lineage["lineage_id"],
                "kind": lineage["kind"],
                "members": [
                    {"release_id": m["release_id"], "element_id": m["element_id"]}
                    for m in lineage["members"]
                ],
            }
            for lineage in artifacts.get("lineages", [])
        ],
        "tracks": [
            {
                "track_id": track["track_id"],
                "anti_pattern_type": track["anti_pattern_type"],
                "catalog": track["catalog"],
                "scope": track["scope"],
                "end": track["end"],
                "ended_at": track.get("ended_at"),
                "lifecycle": track.get("lifecycle"),
                "occurrences": [
                    {
                        "release_id": o["release_id"],
                        "local_instance_id": o["local_instance_id"],
                        "members": o["members"],
                        "transition": o["transition"],
                    }
                    for o in track["occurrences"]
                ],
            }
            for track in artifacts.get("tracks", [])
        ],
        "trends": [trend.model_dump(mode="json") for trend in outputs.trends],
        "untested": [untested.model_dump(mode="json") for untested in outputs.untested],
        "events": [event.model_dump(mode="json", by_alias=True) for event in outputs.events],
        "static_flags": [flag.model_dump(mode="json") for flag in outputs.static_flags],
    }


def _release(
    release: CanonicalRelease,
    ordinal: int | None,
    absence: str | None,
    detection: Mapping[str, Any] | None,
    instances: list[dict[str, Any]],
    lineage_of: Mapping[tuple[str, str], str],
) -> dict[str, Any]:
    element_metrics: dict[str, dict[str, float | None]] = defaultdict(dict)
    system_metrics: dict[str, float | None] = {}
    for observation in (detection or {}).get("observations", []):
        if observation["element_id"] is None:
            system_metrics[observation["metric"]] = observation["value"]
        else:
            element_metrics[observation["element_id"]][observation["metric"]] = observation["value"]

    return {
        "release_id": release.release_id,
        "released_at": release.released_at.isoformat(),
        "ordinal": ordinal,
        "on_timeline": ordinal is not None,
        "absent_because": absence,
        "gate_status": release.gate_status.value,
        "validation_confidence": release.validation_confidence,
        "architecture_style": release.architecture_style.value,
        "c2_validation_ref": release.c2_validation_ref,
        "elements": [
            {
                "id": element.element_id,
                "name": element.name,
                "kind": element.kind,
                "size": element.size,
                "size_unit": element.size_unit,
                "lineage_id": lineage_of.get((release.release_id, element.element_id)),
            }
            for element in release.elements
        ],
        "dependencies": [
            {
                "source": edge.from_id,
                "target": edge.to_id,
                "types": list(edge.types),
                "count": edge.count,
            }
            for edge in release.dependencies
        ],
        "datastore_access": (
            None
            if release.datastore_access is None
            else [access.model_dump(mode="json") for access in release.datastore_access]
        ),
        "detectors_run": list((detection or {}).get("detectors_run", [])),
        "instances": instances,
        "element_metrics": dict(element_metrics),
        "system_metrics": system_metrics,
    }


def _absence(
    release: CanonicalRelease, on_timeline: Mapping[str, int], main_line: re.Pattern[str]
) -> str | None:
    """Why a stored release is not on the run's timeline, or None when it is."""
    if release.release_id in on_timeline:
        return None
    if release.gate_status is GateStatus.EXCLUDED:
        return EXCLUDED
    if main_line.pattern and main_line.search(release.release_id) is None:
        return OFF_MAIN_LINE
    return NOT_IN_RUN


def _lineage_index(lineages: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], str]:
    return {
        (member["release_id"], member["element_id"]): lineage["lineage_id"]
        for lineage in lineages
        for member in lineage["members"]
    }


def _track_index(
    tracks: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (o["release_id"], o["local_instance_id"]): {
            "track_id": track["track_id"],
            "transition": o["transition"],
        }
        for track in tracks
        for o in track["occurrences"]
    }
