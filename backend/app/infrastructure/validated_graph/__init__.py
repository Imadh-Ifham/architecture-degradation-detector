"""The published validated graph on the local filesystem.

Author: Aman Mohamed M.A
Date: 2026-10-19
Description:
    Where a completed run's deliverable is written. One file per run, kept, and
    a `latest` pointer moved by atomic rename.

    A directory rather than a database because the file is the contract: it is
    diffable, it attaches to a report, and it is produced with every database
    switched off.

    **Not named `artifacts`.** It was, and `backend/.gitignore` carries
    `artifacts/`, which matches a directory of that name anywhere in the tree -
    so this package was silently ignored and would have been missing from the
    commit, with the import failing on a fresh clone and nowhere obvious to
    look. The runtime output still goes to `artifacts/`; the code that writes
    it does not live there.
"""

from .validated_graph_file_store import (
    LATEST_FILENAME,
    ValidatedGraphFileStore,
)

__all__ = ["LATEST_FILENAME", "ValidatedGraphFileStore"]
