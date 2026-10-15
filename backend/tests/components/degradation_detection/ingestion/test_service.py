"""M1 end to end: receive, validate, normalise, idempotency, gate, persist; then the timeline."""

import json
import logging
from typing import Any

import pytest
from structlog.testing import capture_logs

from app.components.degradation_detection.config import C3Config, IngestConfig
from app.components.degradation_detection.ingestion import IngestService
from app.components.degradation_detection.ingestion.models import (
    IngestOutcome,
    IngestStatus,
    RawPackage,
)
from app.components.degradation_detection.stub import StubService
from app.domain.canonical_release import GateStatus
from tests.components.degradation_detection.fakes import FixedClock, InMemoryReleaseRepository
from tests.components.degradation_detection.ingestion.packages import payload, raw

CFG = C3Config()


@pytest.fixture
def repo() -> InMemoryReleaseRepository:
    return InMemoryReleaseRepository()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock()


@pytest.fixture
def service(repo: InMemoryReleaseRepository, clock: FixedClock) -> IngestService:
    return IngestService(repo, clock, CFG)


def ingest_one(service: IngestService, package: RawPackage) -> IngestOutcome:
    [outcome] = service.ingest([package]).outcomes
    return outcome


# --- rejections: one per reason; a rejected package never touches the store -----------------


def bad_payload(case: str) -> dict[str, Any]:
    if case == "DUPLICATE_ELEMENT_ID":
        return payload(elements=[{"id": "a"}, {"id": "a"}], dependencies=[])
    if case == "DANGLING_DEPENDENCY":
        return payload(dependencies=[{"from": "a", "to": "ghost"}])
    return payload(elements=[])  # INPUT_SCHEMA_INVALID


@pytest.mark.parametrize(
    "reason", ["INPUT_SCHEMA_INVALID", "DUPLICATE_ELEMENT_ID", "DANGLING_DEPENDENCY"]
)
def test_invalid_package_is_rejected_with_its_reason(
    service: IngestService, repo: InMemoryReleaseRepository, reason: str
) -> None:
    with capture_logs() as logs:
        outcome = ingest_one(service, raw(bad_payload(reason)))

    assert outcome.status is IngestStatus.REJECTED
    assert outcome.reason == reason
    assert outcome.detail
    assert repo.releases == {}
    assert [e["reason"] for e in logs if e.get("log_level") == "warning"] == [reason]


def test_shape_error_detail_names_the_field(service: IngestService) -> None:
    outcome = ingest_one(service, raw(payload(validation_confidence="high")))

    assert outcome.reason == "INPUT_SCHEMA_INVALID"
    assert outcome.detail is not None and "validation_confidence" in outcome.detail


@pytest.mark.parametrize("data", [b"{not json", b"\xff\xfe\x00", b""])
def test_bytes_that_are_not_json_are_rejected(
    service: IngestService, repo: InMemoryReleaseRepository, data: bytes
) -> None:
    outcome = ingest_one(service, RawPackage(source="broken.json", data=data))

    assert (outcome.status, outcome.reason) == (IngestStatus.REJECTED, "INPUT_NOT_JSON")
    assert outcome.source == "broken.json"
    assert repo.releases == {}


def test_json_that_is_not_an_object_is_a_schema_error(service: IngestService) -> None:
    outcome = ingest_one(service, RawPackage(source="list.json", data=b"[1, 2]"))

    assert outcome.reason == "INPUT_SCHEMA_INVALID"


def test_package_over_the_size_cap_is_rejected_before_parsing(
    repo: InMemoryReleaseRepository, clock: FixedClock
) -> None:
    body = raw(payload())
    cfg = C3Config(ingest=IngestConfig(max_package_bytes=len(body.data) - 1))

    [outcome] = IngestService(repo, clock, cfg).ingest([body]).outcomes

    assert (outcome.status, outcome.reason) == (IngestStatus.REJECTED, "PACKAGE_TOO_LARGE")
    assert repo.releases == {}


def test_package_exactly_at_the_size_cap_is_accepted(
    repo: InMemoryReleaseRepository, clock: FixedClock
) -> None:
    body = raw(payload())
    cfg = C3Config(ingest=IngestConfig(max_package_bytes=len(body.data)))

    [outcome] = IngestService(repo, clock, cfg).ingest([body]).outcomes

    assert outcome.status is IngestStatus.STORED


# --- storing --------------------------------------------------------------------------------


def test_valid_package_is_stored_normalised_with_raw_payload_and_time(
    service: IngestService, repo: InMemoryReleaseRepository, clock: FixedClock
) -> None:
    body = payload(dependencies=[{"from": "a", "to": "b"}, {"from": "a", "to": "b"}])

    outcome = ingest_one(service, raw(body))

    assert outcome.status is IngestStatus.STORED
    assert (outcome.system_id, outcome.release_id) == ("tiny", "v1.0.0")
    assert outcome.gate_status is GateStatus.ACCEPTED
    stored = repo.releases[("tiny", "v1.0.0")]
    assert stored.dependencies[0].count == 2
    assert stored.package_hash.startswith("sha256:")
    assert repo.raw[("tiny", "v1.0.0")] == body
    assert repo.ingested_at[("tiny", "v1.0.0")] == clock.value


@pytest.mark.parametrize(
    ("confidence", "gate_status"),
    [(0.7, GateStatus.ACCEPTED), (0.6, GateStatus.DOWNWEIGHTED), (0.3, GateStatus.EXCLUDED)],
)
def test_every_gate_status_is_stored(
    service: IngestService,
    repo: InMemoryReleaseRepository,
    confidence: float,
    gate_status: GateStatus,
) -> None:
    outcome = ingest_one(service, raw(payload(validation_confidence=confidence)))

    assert outcome.status is IngestStatus.STORED
    assert outcome.gate_status is gate_status
    assert repo.releases[("tiny", "v1.0.0")].gate_status is gate_status


def test_unknown_field_is_logged_not_rejected(
    service: IngestService, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)

    outcome = ingest_one(service, raw(payload(colour="blue")))

    assert outcome.status is IngestStatus.STORED
    assert [r.__dict__.get("field") for r in caplog.records] == ["colour"]


# --- idempotency ----------------------------------------------------------------------------


def test_same_package_again_is_a_no_op(
    service: IngestService, repo: InMemoryReleaseRepository
) -> None:
    first = ingest_one(service, raw(payload()))
    again = ingest_one(service, raw(payload(colour="ignored, so same content")))

    assert first.status is IngestStatus.STORED
    assert again.status is IngestStatus.UNCHANGED
    assert again.gate_status is GateStatus.ACCEPTED
    assert len(repo.releases) == 1


def test_same_release_with_different_content_is_a_conflict(
    service: IngestService, repo: InMemoryReleaseRepository
) -> None:
    ingest_one(service, raw(payload()))
    before = repo.releases[("tiny", "v1.0.0")]

    outcome = ingest_one(service, raw(payload(validation_confidence=0.8)))

    assert (outcome.status, outcome.reason) == (IngestStatus.REJECTED, "RELEASE_CONFLICT")
    assert repo.releases[("tiny", "v1.0.0")] is before


def test_same_release_id_in_another_system_is_independent(service: IngestService) -> None:
    outcomes = service.ingest([raw(payload()), raw(payload(system_id="other"))]).outcomes

    assert [o.status for o in outcomes] == [IngestStatus.STORED, IngestStatus.STORED]


def test_report_counts_by_status(service: IngestService) -> None:
    report = service.ingest(
        [raw(payload()), raw(payload()), raw(payload(elements=[]), source="bad.json")]
    )

    assert [o.source for o in report.outcomes] == [
        "tiny__v1.0.0.json",
        "tiny__v1.0.0.json",
        "bad.json",
    ]
    assert report.count(IngestStatus.STORED) == 1
    assert report.count(IngestStatus.UNCHANGED) == 1
    assert report.count(IngestStatus.REJECTED) == 1


# --- timeline -------------------------------------------------------------------------------


def test_timeline_reads_the_store(service: IngestService) -> None:
    service.ingest(
        [
            raw(payload(release_id="v1.1.0", released_at="2025-02-01T00:00:00Z")),
            raw(payload(release_id="v1.0.0", released_at="2025-01-01T00:00:00Z")),
            raw(payload(release_id="v1.2.0", validation_confidence=0.1)),
            raw(payload(system_id="other")),
        ]
    )

    result = service.timeline("tiny")

    assert result.system_id == "tiny"
    assert [e.release.release_id for e in result.entries] == ["v1.0.0", "v1.1.0"]


# --- the synthetic system (plan Section 6.2, day 2 proof) -----------------------------------


def stub_packages() -> list[RawPackage]:
    files = StubService().generate().system_files
    return [
        RawPackage(source=name, data=text.encode("utf-8"))
        for name, text in sorted(files.items())
        if name.endswith(".json")
    ]


def test_stub_system_ingests_as_planted(service: IngestService) -> None:
    report = service.ingest(stub_packages())

    stored = [o for o in report.outcomes if o.status is IngestStatus.STORED]
    [rejected] = [o for o in report.outcomes if o.status is IngestStatus.REJECTED]
    assert len(stored) == 10
    assert (rejected.source, rejected.reason) == (
        "shopfront__v1.3.1-hotfix.json",
        "DANGLING_DEPENDENCY",
    )
    downweighted = [o.release_id for o in stored if o.gate_status is GateStatus.DOWNWEIGHTED]
    assert downweighted == ["v1.5.0"]

    entries = service.timeline("shopfront").entries
    assert [e.release.release_id for e in entries] == [f"v1.{i}.0" for i in range(10)]


def test_stub_system_re_run_is_a_no_op(
    service: IngestService, repo: InMemoryReleaseRepository
) -> None:
    service.ingest(stub_packages())
    before = dict(repo.releases)

    report = service.ingest(stub_packages())

    assert report.count(IngestStatus.UNCHANGED) == 10
    assert report.count(IngestStatus.REJECTED) == 1
    assert report.count(IngestStatus.STORED) == 0
    assert repo.releases == before


def test_report_is_json_serialisable(service: IngestService) -> None:
    report = service.ingest([raw(payload())])

    assert json.loads(report.model_dump_json())["outcomes"][0]["status"] == "STORED"
