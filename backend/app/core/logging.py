"""Structured logging: one JSON object per line.

Decisions the pipeline takes (a package rejected, a detector skipped, a series too short) are
logged with a ``reason`` code so a run can be audited and counted by reason.

Two kinds of logger feed the same output. Components log through ``structlog.get_logger()``.
``app/domain`` and ``app/shared`` may not import structlog, so they use the standard library
with ``extra={"reason": ...}``; those records are rendered by the same formatter.

Entry points (the ``c3`` CLI, later the API) call ``configure_logging`` once. Library code
never does.
"""

import logging
import sys
from typing import TextIO

import structlog
from structlog.typing import Processor

HANDLER_NAME = "c3-json"


def configure_logging(level: int | str = logging.INFO, stream: TextIO | None = None) -> None:
    """Send every log record to ``stream`` (default stderr) as a JSON line.

    Logs go to stderr so stdout stays free for command output. Calling this again replaces
    the previous configuration; handlers installed by anyone else are left alone.
    """
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.set_name(HANDLER_NAME)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            # Standard library records: copy their ``extra`` fields into the event.
            foreign_pre_chain=[*shared, structlog.stdlib.ExtraAdder()],
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(sort_keys=True),
            ],
        )
    )

    root = logging.getLogger()
    for old in [h for h in root.handlers if h.get_name() == HANDLER_NAME]:
        root.removeHandler(old)
    root.addHandler(handler)
    root.setLevel(level)
