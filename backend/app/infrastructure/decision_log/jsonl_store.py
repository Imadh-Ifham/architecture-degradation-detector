"""Append-only decision log, as a file.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    Writes and reads the decision history. One file per repository, one
    decision event per line, new lines added at the end and existing lines
    never touched.

    That is all this does. It does not decide what belongs in the log and it
    does not interpret anything it reads back - the validation component does
    both, and calls this to keep the result.

    Three reasons it lives here rather than inside the component:

    1. The component is not allowed to open files, and a test enforces it.
       Reading a repository and writing a log are the two things it needs the
       outside world for, and both arrive through a port.
    2. A decision log is not one component's idea. Anything that needs to know
       which architectural decisions were in force at a release can read these
       files directly, without importing a line of validation code.
    3. Swapping the file for a table later is then one new class here and no
       change anywhere else.

    Why a file and not a database table. The log's whole job is to still
    answer the same question tomorrow: reading it from the start has to
    rebuild exactly the state it rebuilt yesterday. A file that is only ever
    appended to does that by itself. A table would do it only as long as
    nobody ever updates a row - and nothing in a shared schema stops someone
    doing that, after which the past has quietly changed.

    Events are written a whole batch at a time. One scan's events describe one
    release, so half of them landing would leave a history that never
    happened.
"""

import json
import re
from collections.abc import Sequence
from pathlib import Path

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


class DecisionLogError(RuntimeError):
    """The log for a repository cannot be read or appended to."""


class JsonlDecisionStore:
    """The decision event log for each repository, as a file under one root."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def append(self, repository_id: str, events: Sequence[dict]) -> None:
        """Append these events to the repository's log, creating it if needed."""

        if not events:
            return

        path = self._path(repository_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        lines = [json.dumps(event, sort_keys=True, ensure_ascii=False) for event in events]
        with path.open("a", encoding="utf-8", newline="\n") as log:
            log.write("\n".join(lines) + "\n")

    def replay(self, repository_id: str) -> list[dict]:
        """Return every event recorded for this repository, in order.

        A repository with no log yet has no decisions, not a missing file to
        complain about: the first scan is what creates it. A log with a line
        that will not parse is a different matter and raises, because a
        history that cannot be read in full cannot be replayed at all.
        """

        path = self._path(repository_id)
        if not path.exists():
            return []

        events = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise DecisionLogError(
                    f"line {number} of '{path.name}' is not readable JSON, so the "
                    "decision history cannot be replayed."
                ) from error
        return events

    def _path(self, repository_id: str) -> Path:
        """The log file for one repository.

        The identifier is a path component, so it is reduced to one here
        rather than trusted: it arrives from a request body, and a repository
        called `../../etc` would otherwise write outside the root.
        """

        safe = _UNSAFE.sub("_", repository_id).strip("._ ")
        if not safe:
            raise DecisionLogError(f"'{repository_id}' is not a usable repository id.")
        return self._root / f"{safe}.jsonl"


__all__ = ["DecisionLogError", "JsonlDecisionStore"]
