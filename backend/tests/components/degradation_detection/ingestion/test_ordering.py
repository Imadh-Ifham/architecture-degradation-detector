"""M1 steps 7-9: the timeline is a pure query over the stored releases."""

from typing import Any

from structlog.testing import capture_logs

from app.components.degradation_detection.config import IngestConfig
from app.components.degradation_detection.ingestion.ordering import timeline
from app.components.degradation_detection.models import Timeline
from app.domain.canonical_release import CanonicalRelease, GateStatus
from app.domain.release_package import ReleasePackageV1
from tests.components.degradation_detection.ingestion.packages import canonical_from, payload

CFG = IngestConfig()


def release(
    release_id: str,
    released_at: str,
    gate_status: GateStatus = GateStatus.ACCEPTED,
    **overrides: Any,
) -> CanonicalRelease:
    package = ReleasePackageV1.model_validate(
        payload(release_id=release_id, released_at=released_at, **overrides)
    )
    return canonical_from(package, gate_status)


def ids(result: Timeline) -> list[str]:
    return [entry.release.release_id for entry in result.entries]


def test_orders_by_release_date_not_by_tag_name() -> None:
    result = timeline(
        "tiny",
        [
            release("v1.10.0", "2025-11-01T00:00:00Z"),
            release("v1.9.0", "2025-10-01T00:00:00Z"),
            release("v1.2.0", "2025-03-01T00:00:00Z"),
        ],
        CFG,
    )

    assert ids(result) == ["v1.2.0", "v1.9.0", "v1.10.0"]
    assert [entry.ordinal for entry in result.entries] == [0, 1, 2]


def test_date_wins_even_when_it_contradicts_the_tag() -> None:
    result = timeline(
        "tiny",
        [release("v2.0.0", "2025-01-01T00:00:00Z"), release("v1.0.0", "2025-02-01T00:00:00Z")],
        CFG,
    )

    assert ids(result) == ["v2.0.0", "v1.0.0"]


def test_equal_dates_tie_break_by_semver_then_id() -> None:
    same = "2025-01-01T00:00:00Z"
    result = timeline(
        "tiny",
        [release("v1.10.0", same), release("v1.9.0", same), release("1.9.0", same)],
        CFG,
    )

    # v1.9.0 and 1.9.0 have the same version, so the id decides ("1" < "v").
    assert ids(result) == ["1.9.0", "v1.9.0", "v1.10.0"]


def test_non_semver_tag_sorts_after_semver_on_equal_dates() -> None:
    same = "2025-01-01T00:00:00Z"
    loose = IngestConfig(release_line_regex=".*")
    result = timeline("tiny", [release("nightly", same), release("v1.0.0", same)], loose)

    assert ids(result) == ["v1.0.0", "nightly"]


def test_offsets_are_compared_as_instants() -> None:
    result = timeline(
        "tiny",
        [
            release("v1.0.0", "2025-01-01T03:00:00+05:30"),  # 21:30 UTC the day before
            release("v1.1.0", "2025-01-01T00:00:00Z"),
        ],
        CFG,
    )

    assert ids(result) == ["v1.0.0", "v1.1.0"]


def test_back_ports_are_off_the_main_line() -> None:
    with capture_logs() as logs:
        result = timeline(
            "tiny",
            [
                release("v1.0.0", "2025-01-01T00:00:00Z"),
                release("v1.0.1-hotfix", "2025-01-15T00:00:00Z"),
                release("v1.1.0", "2025-02-01T00:00:00Z"),
            ],
            CFG,
        )

    assert ids(result) == ["v1.0.0", "v1.1.0"]
    assert [e["release_id"] for e in logs if e.get("reason") == "RELEASE_OFF_MAIN_LINE"] == [
        "v1.0.1-hotfix"
    ]


def test_excluded_releases_are_left_out_and_downweighted_kept() -> None:
    result = timeline(
        "tiny",
        [
            release("v1.0.0", "2025-01-01T00:00:00Z"),
            release("v1.1.0", "2025-02-01T00:00:00Z", GateStatus.EXCLUDED),
            release("v1.2.0", "2025-03-01T00:00:00Z", GateStatus.DOWNWEIGHTED),
        ],
        CFG,
    )

    assert ids(result) == ["v1.0.0", "v1.2.0"]
    # Ordinals are positions on this timeline, so they close the gap.
    assert [entry.ordinal for entry in result.entries] == [0, 1]
    assert result.entries[1].release.gate_status is GateStatus.DOWNWEIGHTED


def test_style_and_granularity_drift_are_logged() -> None:
    with capture_logs() as logs:
        timeline(
            "tiny",
            [
                release("v1.0.0", "2025-01-01T00:00:00Z"),
                release("v1.1.0", "2025-02-01T00:00:00Z", architecture_style="monolith"),
                release(
                    "v1.2.0",
                    "2025-03-01T00:00:00Z",
                    architecture_style="monolith",
                    granularity="module",
                ),
            ],
            CFG,
        )

    drift = [(e["reason"], e["release_id"]) for e in logs if e.get("log_level") == "warning"]
    assert drift == [
        ("ARCHITECTURE_STYLE_CHANGED", "v1.1.0"),
        ("GRANULARITY_CHANGED", "v1.2.0"),
    ]


def test_empty_store_gives_an_empty_timeline() -> None:
    result = timeline("tiny", [], CFG)

    assert result == Timeline(system_id="tiny", entries=(), intents=())


def intent(intent_id: str, decision: str = "split a") -> dict[str, Any]:
    return {"intent_id": intent_id, "source_type": "adr", "decision": decision}


def test_same_intent_across_releases_becomes_one_record() -> None:
    result = timeline(
        "tiny",
        [
            # Stored out of order: first/last seen must follow the timeline, not the store.
            release("v1.2.0", "2025-03-01T00:00:00Z", intent=[intent("ADR-1", "split a, done")]),
            release("v1.0.0", "2025-01-01T00:00:00Z", intent=[intent("ADR-1")]),
            release("v1.1.0", "2025-02-01T00:00:00Z", intent=[intent("ADR-1"), intent("ADR-2")]),
        ],
        CFG,
    )

    by_id = {record.intent.intent_id: record for record in result.intents}
    assert [record.intent.intent_id for record in result.intents] == ["ADR-1", "ADR-2"]
    assert (by_id["ADR-1"].first_seen_release, by_id["ADR-1"].last_seen_release) == (
        "v1.0.0",
        "v1.2.0",
    )
    assert by_id["ADR-1"].intent.decision == "split a, done"  # latest statement wins
    assert (by_id["ADR-2"].first_seen_release, by_id["ADR-2"].last_seen_release) == (
        "v1.1.0",
        "v1.1.0",
    )


def test_intents_of_releases_off_the_timeline_are_ignored() -> None:
    result = timeline(
        "tiny",
        [
            release("v1.0.0", "2025-01-01T00:00:00Z"),
            release("v1.1.0", "2025-02-01T00:00:00Z", GateStatus.EXCLUDED, intent=[intent("X")]),
        ],
        CFG,
    )

    assert result.intents == ()
