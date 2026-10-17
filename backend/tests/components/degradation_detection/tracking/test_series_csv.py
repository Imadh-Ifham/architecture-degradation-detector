"""``series.csv``: the series table in long form, one row per point (T-10)."""

from app.components.degradation_detection.models import Series, SeriesPoint
from app.components.degradation_detection.tracking.series_csv import COLUMNS, series_csv
from app.domain.degradation_event import Scope


def series(scope: Scope, subject: str, metric: str, *values: float | None) -> Series:
    return Series(
        scope=scope,
        subject_id=subject,
        metric=metric,
        points=tuple(
            SeriesPoint(ordinal=k, release_id=f"v1.{k}.0", value=v) for k, v in enumerate(values)
        ),
    )


def test_header_then_one_row_per_point_in_table_order() -> None:
    text = series_csv(
        (
            series(Scope.ELEMENT, "LIN-a@v1.0.0", "size", 100.0, 120.0),
            series(Scope.SYSTEM, "tiny", "modularity", 0.5),
        )
    )

    assert text.split("\n") == [
        ",".join(COLUMNS),
        "ELEMENT,LIN-a@v1.0.0,size,0,v1.0.0,100",
        "ELEMENT,LIN-a@v1.0.0,size,1,v1.1.0,120",
        "SYSTEM,tiny,modularity,0,v1.0.0,0.5",
        "",
    ]
    assert COLUMNS == ("scope", "subject_id", "metric", "ordinal", "release_id", "value")


def test_null_is_an_empty_cell_never_zero() -> None:
    text = series_csv((series(Scope.ELEMENT, "LIN-a@v1.0.0", "size_rz", None, 0.0),))

    assert text.split("\n")[1:3] == [
        "ELEMENT,LIN-a@v1.0.0,size_rz,0,v1.0.0,",
        "ELEMENT,LIN-a@v1.0.0,size_rz,1,v1.1.0,0",
    ]


def test_floats_have_fixed_digits_so_noise_does_not_change_the_bytes() -> None:
    text = series_csv((series(Scope.SYSTEM, "tiny", "share", 0.1 + 0.2, 2 / 3, -0.0),))

    assert [line.rsplit(",", 1)[1] for line in text.split("\n")[1:4]] == [
        "0.3",
        "0.666666666667",
        "0",
    ]


def test_empty_table_is_just_the_header() -> None:
    assert series_csv(()) == ",".join(COLUMNS) + "\n"
