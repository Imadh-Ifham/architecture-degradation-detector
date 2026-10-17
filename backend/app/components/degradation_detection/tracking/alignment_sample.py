"""``alignment_sample.csv``: every non-exact alignment decision, for a manual check.

Evaluation (plan Section 8, SO1) needs alignment accuracy against a person's judgement. Exact
matches are left out: they are most of every release and trivially right. A person fills in
``correct``; multi-element decisions list their ids joined with ``;``. Scores have fixed digits
and lines end in LF, so the same run always writes the same bytes.
"""

import csv
import io

from app.components.degradation_detection.tracking.models import AlignmentDecision, TrackingResult

COLUMNS = (
    "from_release_id",
    "to_release_id",
    "from_element_ids",
    "to_element_ids",
    "kind",
    "method",
    "outcome",
    "similarity",
    "name",
    "neighbours",
    "size",
    "runner_up",
    "correct",  # left empty for the person checking the sample
)


def _score(value: float | None) -> str:
    return "" if value is None else f"{value:.4f}"


def _row(d: AlignmentDecision) -> tuple[str, ...]:
    s = d.score
    return (
        d.from_release_id,
        d.to_release_id,
        ";".join(d.from_element_ids),
        ";".join(d.to_element_ids),
        d.kind,
        d.method.value,
        d.outcome.value,
        _score(s.total if s else None),
        _score(s.name if s else None),
        _score(s.neighbours if s else None),
        _score(s.size if s else None),
        _score(d.runner_up),
        "",
    )


def alignment_sample_csv(result: TrackingResult) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    writer.writerows(_row(decision) for decision in result.decisions)
    return out.getvalue()
