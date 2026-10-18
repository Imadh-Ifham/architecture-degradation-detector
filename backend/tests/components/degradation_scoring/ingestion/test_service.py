# Tests for the ingestion service entry point.

from app.components.degradation_scoring import ingestion
from app.components.degradation_scoring.ingestion.service import IngestionService
from tests.components.degradation_scoring.support import (
    FakeEventSource,
    default_config,
    load_fixture,
)


def test_package_exports_only_the_service() -> None:
    assert ingestion.__all__ == ["IngestionService"]
    assert ingestion.IngestionService is IngestionService


def test_ingest_uses_the_configured_confirmed_only_switch() -> None:
    source = FakeEventSource(load_fixture("events/fixture_events.v1.json"))
    payloads = source.fetch("c4-fixture-shop", "v1.5.0")

    default = IngestionService(default_config()).ingest(payloads)
    confirmed_only = IngestionService(default_config(rank_only_confirmed=True)).ingest(payloads)

    assert len(default.eligible) == 10
    assert len(confirmed_only.eligible) == 2
    assert source.requests == [("c4-fixture-shop", "v1.5.0")]
