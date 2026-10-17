"""``series.csv``: the series table in long form, one row per point (plan T-10).

Null is an empty cell, never 0. Floats keep the canonical JSON digits and lines end in LF, so
the same run always writes the same bytes and the file diffs cleanly between runs.
"""

import csv
import io
from collections.abc import Iterable

from app.components.degradation_detection.models import Series
from app.shared.canonical_json import FLOAT_DIGITS

COLUMNS = ("scope", "subject_id", "metric", "ordinal", "release_id", "value")


def _value(value: float | None) -> str:
    return "" if value is None else format(value + 0.0, f".{FLOAT_DIGITS}g")  # -0.0 -> 0


def series_csv(series: Iterable[Series]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    writer.writerows(
        (s.scope.value, s.subject_id, s.metric, p.ordinal, p.release_id, _value(p.value))
        for s in series
        for p in s.points
    )
    return out.getvalue()
