"""Every `c3` invocation configures logging; undo it so no handler outlives the CLI runner."""

import pytest


@pytest.fixture(autouse=True)
def _clean_logging(clean_logging: None) -> None:
    return None
