"""Count the ``reason`` codes logged while a block of code runs.

Decisions are logged with a ``reason`` code (``app/core/logging.py``); an analysis run stores
how many times each one was taken. The counter is a logging handler on the root logger, so it
sees records from both kinds of logger:

* structlog, configured to hand the event dict to the standard library as the record's message;
* the standard library with ``extra={"reason": ...}`` (``app/domain``, ``app/shared``).

It counts what the logging configuration lets through: a record filtered out by the level is
neither written nor counted.
"""

import logging
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager


class _ReasonCounter(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.counts: Counter[str] = Counter()

    def emit(self, record: logging.LogRecord) -> None:
        if isinstance(record.msg, dict):
            reason = record.msg.get("reason")
        else:
            reason = getattr(record, "reason", None)
        if isinstance(reason, str):
            self.counts[reason] += 1


@contextmanager
def count_reasons() -> Iterator[Counter[str]]:
    """Yield a counter of reason codes that fills while the block runs."""
    handler = _ReasonCounter()
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        yield handler.counts
    finally:
        root.removeHandler(handler)
