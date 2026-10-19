"""Git command-line adapter.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Wraps the git executable so no other layer builds git commands itself.
    Every invocation runs git with an argument list (never a shell), a
    timeout, and interactive credential prompts disabled.
"""

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


class GitCommandError(RuntimeError):
    """Raised when a git command exits with a non-zero status."""

    def __init__(self, command: list[str], returncode: int, stderr: str) -> None:
        """Capture the failed command, its exit code and the git stderr output."""

        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(stderr.strip() or f"git exited with status {returncode}")


class GitClient:
    """Thin wrapper around the git command-line interface.

    Arguments are always passed as a list, never through a shell, and `--`
    terminates option parsing so no caller-supplied value can become a flag.
    """

    def __init__(self, timeout_seconds: int = 300) -> None:
        """Store the timeout applied to every git invocation."""

        self._timeout_seconds = timeout_seconds

    def clone(self, url: str, branch: str, destination: Path) -> None:
        """Shallow-clone a single branch of `url` into `destination`."""

        destination.parent.mkdir(parents=True, exist_ok=True)

        # Shallow, single-branch clone: an ingestion workspace only ever needs
        # the tip of the requested branch, so skip the rest of the history.
        #
        # `--` terminates option parsing, so the url can never be read as a flag
        # even if validation upstream were ever circumvented.
        self._run(
            "clone",
            "--depth",
            "1",
            "--single-branch",
            "--branch",
            branch,
            "--",
            url,
            str(destination),
        )

    def clone_at(self, url: str, revision: str, destination: Path) -> None:
        """Clone `url` at an explicit revision into `destination`.

        A tag or branch is fetched shallowly, which is all an analysis needs.
        A bare commit SHA is not a ref, so it is fetched as one object first
        and the full history is the fallback for a server that refuses that.
        Either way the checked-out tree is one revision, never a moving tip.
        """

        destination.parent.mkdir(parents=True, exist_ok=True)

        try:
            self._run(
                "clone",
                "--depth",
                "1",
                "--single-branch",
                "--branch",
                revision,
                "--",
                url,
                str(destination),
            )
            return
        except GitCommandError:
            # Not a ref: most likely a commit SHA. Start again without the
            # shallow branch assumption.
            _discard(destination)

        destination.mkdir(parents=True, exist_ok=True)

        try:
            self._run("init", str(destination))
            self._run("-C", str(destination), "remote", "add", "origin", url)
            self._run(
                "-C", str(destination), "fetch", "--depth", "1", "origin", revision
            )
            self._run("-C", str(destination), "checkout", "--detach", "FETCH_HEAD")
        except GitCommandError:
            # A server that refuses to serve a bare SHA. The full clone is the
            # only way left to obtain that exact tree.
            _discard(destination)
            self._run("clone", "--no-checkout", "--", url, str(destination))
            self._run("-C", str(destination), "checkout", "--detach", revision)

    def head_commit(self, repository: Path) -> str:
        """Return the full commit SHA currently checked out in `repository`."""

        return self._run("-C", str(repository), "rev-parse", "HEAD").strip()

    def is_tag(self, repository: Path, revision: str) -> bool:
        """Report whether `revision` names an existing tag."""

        return (
            self._try(
                "-C",
                str(repository),
                "rev-parse",
                "--verify",
                "--quiet",
                f"refs/tags/{revision}^{{commit}}",
            )
            is not None
        )

    def tag_date(self, repository: Path, tag: str) -> datetime | None:
        """Return an annotated tag's own date, or None for a lightweight tag.

        A lightweight tag carries no publication date. Returning the commit
        date instead would present "when the work was written" as "when the
        release was cut", which is the confusion this method exists to avoid.
        """

        output = self._try(
            "-C",
            str(repository),
            "for-each-ref",
            "--format=%(taggerdate:iso-strict)",
            f"refs/tags/{tag}",
        )
        return _parse_date(output)

    def commit_date(self, repository: Path, revision: str = "HEAD") -> datetime | None:
        """Return the author date of a revision, or None when git cannot say."""

        output = self._try(
            "-C", str(repository), "log", "-1", "--format=%aI", revision, "--"
        )
        return _parse_date(output)

    def _try(self, *arguments: str) -> str | None:
        """Run git and return stdout, or None when it fails.

        Used only for questions whose answer may legitimately be "nothing"
        (an unknown tag, no date). Everything that must succeed still uses
        `_run`, so a real failure is still an exception.
        """

        try:
            return self._run(*arguments)
        except GitCommandError:
            return None

    def _run(self, *arguments: str) -> str:
        """Run `git <arguments>` and return stdout, raising on failure."""

        command = ["git", *arguments]

        # GIT_TERMINAL_PROMPT=0 stops git from blocking forever on an
        # interactive credential prompt (for example, a private repository).
        environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                check=False,
                env=environment,
            )
        except subprocess.TimeoutExpired as error:
            raise GitCommandError(
                command,
                -1,
                f"timed out after {self._timeout_seconds} seconds",
            ) from error

        # check=False keeps the failure detail in our own exception type.
        if completed.returncode != 0:
            raise GitCommandError(command, completed.returncode, completed.stderr)

        return completed.stdout


def _discard(path: Path) -> None:
    """Remove a half-built clone without letting cleanup mask the real error."""

    shutil.rmtree(path, ignore_errors=True)


def _parse_date(value: str | None) -> datetime | None:
    """Read an ISO 8601 timestamp from git, preserving its timezone."""

    if not value:
        return None

    text = value.strip()

    if not text:
        return None

    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
