"""Fixtures shared by the whole test suite."""

import logging
from collections.abc import Iterator

import pytest
import structlog

from app.core.logging import HANDLER_NAME


@pytest.fixture
def clean_logging() -> Iterator[None]:
    """Undo ``configure_logging`` after a test, so its handler never outlives its stream."""
    root = logging.getLogger()
    level = root.level
    yield
    for handler in [h for h in root.handlers if h.get_name() == HANDLER_NAME]:
        root.removeHandler(handler)
    root.setLevel(level)
    structlog.reset_defaults()
