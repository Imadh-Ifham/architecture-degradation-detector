"""Repository source validation.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Validates the url and branch a client asks us to clone, and redacts
    credentials from urls before they are logged, stored or returned.

    Validation runs before git does, so a rejected source can never reach an
    argument parser.
"""

import re
from urllib.parse import urlsplit

from app.components.architecture_recovery.repository_ingestion.errors import (
    InvalidRepositorySource,
)

# Only absolute remote urls are accepted. Local paths and `file://` are
# rejected so a request cannot make the server read arbitrary local files.
_ALLOWED_URL_SCHEMES = ("https://", "http://", "ssh://", "git://")

# The scp-like form, for example `git@github.com:owner/repo.git`.
_SCP_LIKE_URL = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+:[^\s]+$")

# Matches `scheme://user:password@` and keeps the scheme so only the userinfo
# (the part that can hold a token) is stripped.
_CREDENTIALS = re.compile(r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)[^/@\s]+@")

# Characters that `git check-ref-format` refuses in a ref name.
_FORBIDDEN_BRANCH_CHARACTERS = re.compile(r"[\s~^:?*\[\\]")

# Sequences that `git check-ref-format` refuses in a ref name.
_FORBIDDEN_BRANCH_SEQUENCES = ("..", "@{", "//")

# Shape of the ids this component generates: lowercase, no path separators.
_REPOSITORY_ID = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")


def validate_url(url: str) -> str:
    """Return the trimmed url when it is an acceptable remote source.

    Raises `InvalidRepositorySource` otherwise.
    """

    candidate = url.strip()

    if not candidate:
        raise InvalidRepositorySource("Repository url must not be empty.")

    # A leading '-' would be parsed by git as an option rather than a url.
    if candidate.startswith("-"):
        raise InvalidRepositorySource("Repository url must not start with '-'.")

    if _SCP_LIKE_URL.match(candidate):
        return candidate

    # urlsplit guards against a scheme with no host, such as a bare "https://".
    if candidate.startswith(_ALLOWED_URL_SCHEMES) and urlsplit(candidate).netloc:
        return candidate

    schemes = ", ".join(_ALLOWED_URL_SCHEMES)
    raise InvalidRepositorySource(
        f"Repository url must be an absolute remote url using one of: {schemes} "
        "or the scp-like form user@host:path."
    )


def validate_branch(branch: str) -> str:
    """Return the trimmed branch name when it is a valid git ref.

    Mirrors the rules of `git check-ref-format`, so an invalid branch fails
    with a clear message instead of an opaque git error.
    """

    return _validate_ref(branch, "Branch name")


def validate_release_tag(tag: str) -> str:
    """Return the trimmed release tag when it is a valid git ref.

    A tag is a ref like a branch, so the same rules apply; only the wording of
    a rejection changes, because "Branch name must not..." is not a sentence
    anybody who typed a tag expects to read.
    """

    return _validate_ref(tag, "Release tag")


def _validate_ref(value: str, label: str) -> str:
    """Validate a git ref name, naming it the way the caller thinks of it."""

    candidate = value.strip()

    if not candidate:
        raise InvalidRepositorySource(f"{label} must not be empty.")

    # A leading '-' would be parsed by git as an option (for example
    # "--upload-pack=..."), so reject it outright.
    if candidate.startswith("-"):
        raise InvalidRepositorySource(f"{label} must not start with '-'.")

    if candidate == "@":
        raise InvalidRepositorySource(f"{label} must not be '@'.")

    if candidate.startswith("/") or candidate.endswith("/"):
        raise InvalidRepositorySource(f"{label} must not start or end with '/'.")

    if candidate.endswith("."):
        raise InvalidRepositorySource(f"{label} must not end with '.'.")

    if candidate.endswith(".lock"):
        raise InvalidRepositorySource(f"{label} must not end with '.lock'.")

    if _FORBIDDEN_BRANCH_CHARACTERS.search(candidate):
        raise InvalidRepositorySource(
            f"{label} must not contain whitespace or any of: ~ ^ : ? * [ \\"
        )

    if any(sequence in candidate for sequence in _FORBIDDEN_BRANCH_SEQUENCES):
        raise InvalidRepositorySource(
            f"{label} must not contain '..', '@{{' or '//'."
        )

    return candidate


def is_valid_repository_id(repository_id: str) -> bool:
    """Report whether the id matches the shape this component generates.

    Used to reject path traversal before an id is used on the filesystem.
    """

    return bool(_REPOSITORY_ID.match(repository_id))


def redact_credentials(text: str) -> str:
    """Strip `user:password@` from any url embedded in the given text."""

    return _CREDENTIALS.sub(r"\g<scheme>***@", text)
