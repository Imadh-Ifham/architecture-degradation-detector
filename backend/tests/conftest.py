"""Shared pytest configuration for the backend test suite.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Keeps the fixture repositories out of test collection. The multi-service
    fixture deliberately contains files named like tests (for example
    `services/checkout/tests/test_service.py`) so the inventory can be checked
    against a realistic layout; those files must not be collected or imported
    as part of this suite.
"""

import logging
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
import structlog

from app.core.logging import HANDLER_NAME

collect_ignore_glob = ["fixtures/*"]


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


@pytest.fixture(scope="session", autouse=True)
def subject_trees():
    """Make sure the generated subject working trees exist.

    They are inputs the validation fixtures were recorded from, and they are
    generated rather than committed - about a hundred files of scaffolding
    whose only job is to be walked. Regenerated here so a fresh clone runs the
    suite without a setup step.
    """

    sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "validation"))
    import build_subject_tree

    build_subject_tree.build_all()
