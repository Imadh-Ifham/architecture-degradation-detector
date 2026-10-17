"""SystemClock: the real Clock port, used by entry points."""

import datetime as dt

from app.shared.clock import SystemClock


def test_system_clock_returns_aware_utc_now() -> None:
    before = dt.datetime.now(dt.UTC)

    now = SystemClock().now()

    assert now.tzinfo is dt.UTC
    assert before <= now <= dt.datetime.now(dt.UTC)
