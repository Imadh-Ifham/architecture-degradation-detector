"""Structured logging: every log line is one JSON object, and decisions carry a ``reason`` code."""

import io
import json
import logging
from typing import Any

import pytest
import structlog

from app.core.logging import HANDLER_NAME, configure_logging
from app.domain.boundary import UNKNOWN_FIELD_IGNORED, BoundaryModel

pytestmark = pytest.mark.usefixtures("clean_logging")


class Probe(BoundaryModel):
    known: int


def entries(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_structlog_event_is_one_json_line_with_its_reason() -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)

    structlog.get_logger("c3.detection").info(
        "detector_skipped", reason="CATALOG_INPUT_MISSING", detector="SharedPersistence"
    )

    [entry] = entries(stream)
    assert entry["event"] == "detector_skipped"
    assert entry["reason"] == "CATALOG_INPUT_MISSING"
    assert entry["detector"] == "SharedPersistence"
    assert entry["level"] == "info"
    assert entry["logger"] == "c3.detection"
    assert entry["timestamp"].endswith("Z")


def test_stdlib_record_keeps_its_extra_fields() -> None:
    """app/domain cannot import structlog, so it logs through stdlib ``extra``."""
    stream = io.StringIO()
    configure_logging(stream=stream)

    Probe.model_validate({"known": 1, "surprise": 2})

    [entry] = entries(stream)
    assert entry["event"] == UNKNOWN_FIELD_IGNORED
    assert entry["reason"] == UNKNOWN_FIELD_IGNORED
    assert entry["model"] == "Probe"
    assert entry["field"] == "surprise"
    assert entry["level"] == "warning"
    assert entry["logger"] == "app.domain.boundary"


def test_events_below_the_level_are_dropped() -> None:
    stream = io.StringIO()
    configure_logging("WARNING", stream=stream)

    structlog.get_logger("c3").info("quiet")
    logging.getLogger("c3").info("quiet")
    structlog.get_logger("c3").warning("loud")

    assert [e["event"] for e in entries(stream)] == ["loud"]


def test_configuring_twice_does_not_duplicate_lines() -> None:
    first, second = io.StringIO(), io.StringIO()
    configure_logging(stream=first)
    configure_logging(stream=second)

    structlog.get_logger("c3").info("once")

    assert first.getvalue() == ""
    assert len(entries(second)) == 1
    assert [h.get_name() for h in logging.getLogger().handlers].count(HANDLER_NAME) == 1


def test_other_handlers_are_left_alone() -> None:
    other = logging.NullHandler()
    logging.getLogger().addHandler(other)
    try:
        configure_logging(stream=io.StringIO())

        assert other in logging.getLogger().handlers
    finally:
        logging.getLogger().removeHandler(other)


def test_exception_is_rendered_into_the_line() -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        structlog.get_logger("c3").exception("run_failed", reason="RUN_FAILED")

    [entry] = entries(stream)
    assert entry["level"] == "error"
    assert "RuntimeError: boom" in entry["exception"]
