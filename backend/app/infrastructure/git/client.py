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

    def __init__(self, command: list[str], returncode: int, stderr: str | None) -> None:
        """Capture the failed command, its exit code and the git stderr output.

        `stderr` may be absent. A reader thread that fails while decoding git's
        output leaves it unset, and raising while describing a failure loses the
        failure: the caller sees an `AttributeError` instead of the git error,
        and an exception handler written for this type does not catch it.
        """

        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(
            (stderr or "").strip() or f"git exited with status {returncode}"
        )


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

        A revision that does not exist is answered before the full clone: a
        mistyped tag is the most common way this fails, and cloning a large
        repository only to discover it is not there costs minutes and produces
        an error about `checkout`'s grammar rather than about the tag.
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
            return
        except GitCommandError:
            # Either a server that refuses to serve a bare SHA, or a revision
            # that does not exist at all. The remote can answer which, without
            # transferring a repository to find out.
            _discard(destination)
            self._refuse_an_absent_revision(url, revision)

        self._run("clone", "--no-checkout", "--", url, str(destination))

        try:
            self._run("-C", str(destination), "checkout", "--detach", revision)
        except GitCommandError as error:
            # Belt and braces: git reports an unknown revision passed to
            # `checkout --detach` as "does not take a path argument", which
            # says nothing about the revision being absent.
            raise GitCommandError(
                error.command, error.returncode, _absent_revision_message(revision)
            ) from error

    def _refuse_an_absent_revision(self, url: str, revision: str) -> None:
        """Raise naming the missing revision, when the remote does not serve it.

        Only refs can be checked this way: a bare commit SHA is not listed by
        `ls-remote`, so a SHA falls through to the full clone. When the remote
        cannot be listed, nothing is concluded and the caller tries the clone.
        """

        refs = self._remote_refs(url)

        if refs is None or _is_commit_sha(revision) or revision in refs:
            return

        near = sorted(
            {
                name
                for name in refs
                if name.lstrip("vV") == revision.lstrip("vV")
            }
        )
        message = _absent_revision_message(revision, near)

        raise GitCommandError(
            ["git", "ls-remote", "--refs", url], 128, message
        )

    def _remote_refs(self, url: str) -> set[str] | None:
        """Every tag and branch name the remote serves, or None if unlistable.

        Names are returned as a caller would type them: `3.1.0` and
        `release/v3.1.0`, not `refs/tags/3.1.0`.
        """

        output = self._try("ls-remote", "--refs", "--tags", "--heads", url)

        if output is None:
            return None

        names: set[str] = set()

        for line in output.splitlines():
            _, _, reference = line.partition("\t")

            for prefix in ("refs/tags/", "refs/heads/"):
                if reference.startswith(prefix):
                    names.add(reference[len(prefix) :])

        return names

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

        # core.longpaths is set per invocation rather than left to the machine.
        # Windows refuses a path over 260 characters, and a repository with deep
        # directories checks out by hand - from a short working directory - and
        # fails under a workspace root, for no reason the error names. Passing it
        # here means the behaviour travels with the code instead of depending on
        # whether somebody ran `git config --global`. It is ignored elsewhere.
        command = ["git", "-c", "core.longpaths=true", *arguments]

        # GIT_TERMINAL_PROMPT=0 stops git from blocking forever on an
        # interactive credential prompt (for example, a private repository).
        environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

        try:
            # Decoded as UTF-8 explicitly. `text=True` alone decodes with the
            # locale codec, which on Windows is cp1252 - and git writes the
            # names of the files it checks out to stderr. One path outside that
            # codec kills the reader thread, which leaves stderr unset and
            # turns a reportable git failure into a decoding error about a
            # repository that cloned perfectly well by hand.
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
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


def _is_commit_sha(revision: str) -> bool:
    """Whether a revision is a full commit SHA, which `ls-remote` cannot list."""

    return len(revision) == 40 and all(
        character in "0123456789abcdefABCDEF" for character in revision
    )


def _absent_revision_message(revision: str, near: list[str] | None = None) -> str:
    """Say that a revision is not in the repository, and what is.

    A near miss is named when one exists, because the common mistake is a
    tag typed with the wrong prefix - `v3.1.0` where the repository tags
    `3.1.0` - and the answer is then one edit away rather than a hunt.
    """

    message = (
        f"'{revision}' is not a tag, branch or commit in this repository."
    )

    if near:
        message += f" Did you mean {', '.join(near)}?"

    return message

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
