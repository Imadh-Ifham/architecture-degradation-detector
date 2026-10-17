"""The real clock. Code that needs the time takes a ``Clock`` port, so tests can fix it."""

import datetime as dt


class SystemClock:
    def now(self) -> dt.datetime:
        """The current time, timezone-aware, in UTC."""
        return dt.datetime.now(dt.UTC)
