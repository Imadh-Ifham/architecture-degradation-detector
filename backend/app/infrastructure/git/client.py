"""Git command-line adapter.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Wraps the git executable so no other layer builds git commands itself.
    Every invocation runs git with an argument list (never a shell), a
    timeout, and interactive credential prompts disabled.
"""

import os
import subprocess
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

    def head_commit(self, repository: Path) -> str:
        """Return the full commit SHA currently checked out in `repository`."""

        return self._run("-C", str(repository), "rev-parse", "HEAD").strip()

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
