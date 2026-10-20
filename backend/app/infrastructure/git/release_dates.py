"""When a release was actually cut.

Author: Aman Mohamed M.A
Date: 2026-10-19
Description:
    Reads a release tag's date out of a local checkout, and says which field
    it came from.

    **Why not the committer date, which is what everybody reaches for first.**
    `git log -1 --format=%cI <tag>` returns the *committer* date, and that is
    rewritten by every rebase, cherry-pick, amend and filter-branch. On a
    repository whose history is tidied before release it reads as the day
    somebody last replayed the commit - which, for a commit replayed today,
    is today. A timeline ordered by it is ordered by editing activity.

    So three sources, in this order, and the one that answered is published
    beside the date:

      tagger   an annotated tag's own date. When the release was cut, and it
               survives the history underneath being rewritten
      author   the tagged commit's author date. When the work was written;
               rewriting preserves it
      caller   whatever the person asking for the run supplied

    A release with none of the three gets no date. Nothing is guessed: a
    plausible wrong date orders a timeline wrongly and cannot be told apart
    from a right one.

    This runs git itself rather than extending the shared `GitClient`, which
    belongs to another component and exposes cloning and the head commit. The
    safety posture is copied deliberately: an argument list and never a shell,
    a timeout, and interactive prompts disabled.
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path

from app.domain.validated_architecture import ReleaseDateSource
from app.infrastructure.workspace.checkouts import WorkspaceCheckouts

TIMEOUT_SECONDS = 15
"""Long enough for a local read, short enough that a wedged git does not hold
a run open. Nothing here talks to a network."""


class ReleaseDateReader:
    """Reads the date of one release tag from a checkout on disk."""

    def __init__(self, workspace_root: Path, checkout_subdirectory: str = "") -> None:
        """Bind the reader to the workspace, and to where a checkout sits in it.

        The same two-part layout the artifact reader uses: ingestion keeps the
        working tree one level down, beside the files it writes about the tree,
        and that is the caller's knowledge rather than this reader's.
        """

        self._checkouts = WorkspaceCheckouts(Path(workspace_root), checkout_subdirectory)

    def read(
        self, repository_id: str, release_id: str
    ) -> tuple[datetime, ReleaseDateSource] | None:
        """Return the release's date and where it came from, or `None`.

        `None` rather than an exception. A repository that is not in the
        workspace, a tag that is not in a shallow clone and a release named
        without a tag at all are all ordinary situations, and the run
        continues without a date rather than failing over one.
        """

        # The release's own checkout: a tag date read from another release's
        # tree would date this one with somebody else's tag.
        checkout = self._checkouts.find(repository_id, release_id)
        if checkout is None or not (checkout / ".git").exists():
            return None

        tagged = self._tagger_date(checkout, release_id)
        if tagged is not None:
            return tagged, ReleaseDateSource.TAGGER

        authored = self._author_date(checkout, release_id)
        if authored is not None:
            return authored, ReleaseDateSource.AUTHOR

        return None

    def _tagger_date(self, checkout: Path, release_id: str) -> datetime | None:
        """An annotated tag's own date, which is when the release was cut.

        Empty for a lightweight tag, which carries no date of its own - and
        then the author date below is the honest answer rather than a date
        invented for it.
        """

        answer = self._run(
            checkout,
            "for-each-ref",
            "--format=%(taggerdate:iso-strict)",
            f"refs/tags/{release_id}",
        )
        return _parse(answer)

    def _author_date(self, checkout: Path, release_id: str) -> datetime | None:
        """The tagged commit's author date, which rewriting preserves."""

        return _parse(
            self._run(checkout, "log", "-1", "--format=%aI", release_id, "--")
        )

    def _run(self, checkout: Path, *arguments: str) -> str:
        """Run one read-only git command, or return nothing it can answer with."""

        command = ["git", "-C", str(checkout), *arguments]
        environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                check=False,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired):
            # git missing, or wedged. Neither is a reason to fail a validation
            # run that has nothing to do with git.
            return ""

        if completed.returncode != 0:
            # An unknown revision, which is what a tag absent from a shallow
            # clone looks like. Expected, and not an error here.
            return ""
        return completed.stdout.strip()


def _parse(value: str) -> datetime | None:
    """Read an ISO 8601 timestamp, or nothing at all."""

    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
