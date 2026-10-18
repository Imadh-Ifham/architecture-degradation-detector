"""count_reasons: how many log records carried each ``reason`` code while a block ran."""

import io
import logging
from collections.abc import Iterator

import pytest
import structlog

from app.core.logging import configure_logging
from app.shared.reason_counter import count_reasons


@pytest.fixture(autouse=True)
def _json_logging(clean_logging: None) -> Iterator[None]:
    configure_logging("INFO", stream=io.StringIO())
    yield


def test_counts_structlog_reasons() -> None:
    log = structlog.get_logger()

    with count_reasons() as counts:
        log.info("SERIES_TOO_SHORT", reason="SERIES_TOO_SHORT")
        log.info("SERIES_TOO_SHORT", reason="SERIES_TOO_SHORT")
        log.warning("ALIAS_CONFLICT", reason="ALIAS_CONFLICT")

    assert counts == {"SERIES_TOO_SHORT": 2, "ALIAS_CONFLICT": 1}


def test_counts_standard_library_reasons() -> None:
    """``app/domain`` and ``app/shared`` log through the standard library with ``extra``."""
    with count_reasons() as counts:
        logging.getLogger("app.domain.x").warning("ignored", extra={"reason": "UNKNOWN_FIELD"})

    assert counts == {"UNKNOWN_FIELD": 1}


def test_records_without_a_reason_are_not_counted() -> None:
    with count_reasons() as counts:
        structlog.get_logger().info("hello", detail=1)
        logging.getLogger("x").warning("plain")

    assert counts == {}


def test_only_records_inside_the_block_are_counted() -> None:
    log = structlog.get_logger()
    log.info("before", reason="BEFORE")

    with count_reasons() as counts:
        log.info("inside", reason="INSIDE")
    log.info("after", reason="AFTER")

    assert counts == {"INSIDE": 1}


def test_the_handler_is_removed_even_when_the_block_raises() -> None:
    handlers = list(logging.getLogger().handlers)

    with pytest.raises(RuntimeError), count_reasons():
        raise RuntimeError("boom")

    assert logging.getLogger().handlers == handlers


def test_records_below_the_configured_level_are_not_counted() -> None:
    """The counter sees what the logging configuration lets through, nothing more."""
    with count_reasons() as counts:
        structlog.get_logger().debug("detail", reason="DEBUG_ONLY")

    assert counts == {}
