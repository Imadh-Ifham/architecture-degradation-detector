"""``report.md``: one stored run as markdown tables.

Everything is in a fixed order (releases in timeline order, events in export order, everything
else sorted by name), so the same stored run always gives the same text, whether it comes from
memory or from the database. Nothing here ranks events: C4 does [locked decision 6].
"""

from collections import Counter
from collections.abc import Iterable, Sequence

from app.components.degradation_detection.report.models import plot_path
from app.domain.analysis_run import RunStatus, StaticFlag, StoredRun
from app.domain.degradation_event import DegradationEventV2, Scope


def subject_label(event: DegradationEventV2) -> str:
    """What the event is about, as a reader knows it: element id, instance track or system."""
    if event.scope is Scope.ELEMENT and event.element_id is not None:
        return event.element_id
    if event.scope is Scope.INSTANCE and event.instance_id is not None:
        return event.instance_id
    return event.system_id


def render_markdown(stored: StoredRun) -> str:
    sections = [
        _header(stored),
        _releases(stored),
        _series(stored),
        _events(stored.outputs.events),
        _baseline(stored),
        _run_details(stored),
    ]
    if stored.run.status is RunStatus.FAILED:
        sections.insert(1, f"## Error\n\n```\n{stored.run.error}\n```")
    return "\n\n".join(sections) + "\n"


def _table(header: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    lines = [_row(header), _row(["---"] * len(header))]
    lines.extend(_row(row) for row in rows)
    return "\n".join(lines)


def _row(cells: Sequence[object]) -> str:
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def _header(stored: StoredRun) -> str:
    run = stored.run
    libraries = ", ".join(f"{name} {version}" for name, version in sorted(run.lib_versions.items()))
    finished = run.finished_at.isoformat() if run.finished_at else "-"
    details = _table(
        ["Run", run.run_id],
        [
            ["System", run.system_id],
            ["Status", run.status.value],
            ["Started", run.started_at.isoformat()],
            ["Finished", finished],
            ["Config hash", f"`{run.config_hash}`"],
            ["Code version", run.code_version],
            ["Libraries", libraries],
        ],
    )
    return f"# C3 analysis run {run.run_id}\n\n{details}"


def _releases(stored: StoredRun) -> str:
    counts = Counter((i.release_id, i.anti_pattern_type) for i in stored.outputs.instances)
    types = sorted({i.anti_pattern_type for i in stored.outputs.instances})
    rows = []
    for release in stored.run.releases:
        per_type = [counts[(release.release_id, t)] for t in types]
        rows.append(
            [
                release.ordinal,
                release.release_id,
                release.released_at.date().isoformat(),
                release.gate_status.value,
                *per_type,
                sum(per_type),
            ]
        )
    table = _table(["#", "Release", "Released", "Gate", *types, "Total"], rows)
    return f"## Releases\n\nAnti-pattern instances M2 found in each release.\n\n{table}"


def _series(stored: StoredRun) -> str:
    out = stored.outputs
    rows = [
        [
            scope.value,
            sum(1 for t in out.trends if t.scope is scope),
            sum(1 for t in out.trends if t.scope is scope and t.is_significant and t.is_worsening),
            sum(1 for u in out.untested if u.scope is scope),
        ]
        for scope in Scope
    ]
    text = (
        "## Series\n\nEvery series M4 tested (Mann-Kendall, Sen's slope, Benjamini-Hochberg "
        "across the run) and every series it did not test [D-03].\n\n"
        + _table(["Scope", "Tested", "Significant worsening", "Not tested"], rows)
    )
    reasons = Counter(u.reason for u in out.untested)
    if reasons:
        text += "\n\nNot tested, by reason:\n\n" + _table(
            ["Reason", "Series"], sorted(reasons.items())
        )
    return text


def _metrics_cell(event: DegradationEventV2) -> str:
    return "; ".join(
        f"{m.metric} (q={m.q_value:.2g}, Sen's slope "
        f"{'-' if m.sen_slope is None else format(m.sen_slope, '+.3g')}/release)"
        for m in event.affected_metrics
    )


def _events(events: Sequence[DegradationEventV2]) -> str:
    title = f"## Events ({len(events)})"
    if not events:
        return f"{title}\n\nNo events."
    rows = [
        [
            e.event_id,
            e.scope.value,
            e.anti_pattern_type,
            subject_label(e),
            f"{e.window.start_release}..{e.window.end_release}",
            e.lifecycle.value if e.lifecycle else "-",
            _metrics_cell(e),
            f"[plot]({plot_path(e.event_id)})",
        ]
        for e in events
    ]
    header = ["Event", "Scope", "Anti-pattern", "Subject", "Window", "Lifecycle", "Metrics", "Plot"]
    return (
        f"{title}\n\nListed in export order (scope, subject, anti-pattern type). "
        "C3 does not rank events: ranking is C4's job.\n\n" + _table(header, rows)
    )


def _has_event(element_id: str, events: Sequence[DegradationEventV2]) -> bool:
    return any(e.element_id == element_id or element_id in e.members for e in events)


def _baseline(stored: StoredRun) -> str:
    flags: Sequence[StaticFlag] = stored.outputs.static_flags
    last = stored.run.releases[-1].release_id if stored.run.releases else "-"
    intro = (
        f"## Static-threshold baseline\n\nWhat a fixed-threshold tool would flag at the last "
        f"release ({last}). For comparison only: C3 decides degradation by a trend, never by a "
        "fixed threshold."
    )
    if not flags:
        return f"{intro}\n\nNo element is above a fixed threshold."
    events = stored.outputs.events
    rows = [
        [
            f.element_id,
            f"{f.metric} > {f.threshold:g}",
            f"{f.value:g}",
            "yes" if _has_event(f.element_id, events) else "no",
        ]
        for f in flags
    ]
    elements = sorted({f.element_id for f in flags})
    with_event = sum(1 for element in elements if _has_event(element, events))
    summary = (
        f"{len(flags)} flags on {len(elements)} elements at {last}; "
        f"{with_event} of these elements has a C3 event."
    )
    table = _table(["Element", "Rule", "Value", "C3 event on this element"], rows)
    return f"{intro}\n\n{table}\n\n{summary}"


def _run_details(stored: StoredRun) -> str:
    run = stored.run
    timings = _table(
        ["Stage", "Seconds"], [[stage, f"{s:.3f}"] for stage, s in sorted(run.timings.items())]
    )
    if run.reason_counts is None:
        reasons = (
            "Reason codes were not counted: logging was not routed through the standard library."
        )
    else:
        reasons = _table(["Reason", "Count"], sorted(run.reason_counts.items()))
    return f"## Run\n\nTimings:\n\n{timings}\n\nReason codes logged:\n\n{reasons}"
