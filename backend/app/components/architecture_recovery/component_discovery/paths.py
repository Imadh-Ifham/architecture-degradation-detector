"""Path and name helpers for component discovery.

Author: Imadh Ifham
Date: 2026-10-15
Description:
    Small, dependency-free helpers for comparing repository-relative paths and
    normalising names. Shared by candidate collection and identity resolution so
    both agree on what "the same name" and "under that directory" mean.

    All paths handled here are repository-relative POSIX paths taken from the
    inventory, never absolute filesystem paths, so nothing in this module can
    reach outside the analysed repository.
"""

import re
from pathlib import PurePosixPath


#: Directory recorded for a path at the repository root.
ROOT_DIRECTORY = "."

#: Characters removed when normalising a name for comparison.
_NON_IDENTIFIER = re.compile(r"[^a-z0-9]+")


def normalize_name(value: str) -> str:
    """Reduce a name to a comparable key.

    Case and separator differences are ignored, so `CartService`,
    `cart-service` and `cartservice` all reduce to `cartservice`. Suffixes are
    deliberately *not* stripped: treating `orders` and `orderservice` as the
    same thing would merge unrelated components.
    """

    return _NON_IDENTIFIER.sub("", value.lower())


def name_keys(*values: str | None) -> set[str]:
    """Return the non-empty normalised keys for the given names."""

    keys = set()

    for value in values:
        if not value:
            continue

        key = normalize_name(value)

        if key:
            keys.add(key)

    return keys


def directory_of(relative_path: str) -> str:
    """Return the directory holding a repository-relative path."""

    parent = str(PurePosixPath(relative_path).parent)

    return parent if parent not in ("", ".") else ROOT_DIRECTORY


def basename_of(relative_path: str) -> str:
    """Return the final path segment of a repository-relative path."""

    return PurePosixPath(relative_path).name


def normalize_context(value: str) -> str:
    """Normalise a declared build context path into a repository-relative form.

    Handles the Compose spelling of a local context (`./web`, `../shared` is left
    alone because it escapes the repository and cannot be resolved here).
    """

    candidate = value.strip().replace("\\", "/")

    while candidate.startswith("./"):
        candidate = candidate[2:]

    candidate = candidate.rstrip("/")

    if candidate.startswith(".."):
        # Outside the repository; there is nothing to resolve it against.
        return ""

    return candidate or ROOT_DIRECTORY


def normalize_image(value: str) -> str:
    """Reduce an image reference to the part that identifies the image."""

    reference = value.strip()

    # Drop a digest, then a tag, leaving repository:path.
    reference = reference.split("@", 1)[0]

    # A tag is only after the final colon and is not a registry port, so a
    # colon followed by a non-numeric suffix is a tag.
    head, separator, tail = reference.rpartition(":")

    if separator and head and not tail.isdigit():
        reference = head

    return reference.lower()


def is_within(path: str, root: str | None) -> bool:
    """Report whether a repository-relative path lies at or under a directory.

    The comparison is segment-aware, so `src/cart` is not treated as containing
    `src/cartservice`. The repository root contains everything; an unknown root
    contains nothing.
    """

    if not root:
        return False

    if root == ROOT_DIRECTORY:
        return True

    return path == root or path.startswith(f"{root}/")


def sort_key_depth(path: str) -> tuple[int, str]:
    """Return a deterministic ordering key for a path, shallowest first."""

    if path in ("", ROOT_DIRECTORY):
        return (0, "")

    return (len(PurePosixPath(path).parts), path)


def shallowest(paths: list[str]) -> str | None:
    """Return the shallowest of the given paths, breaking ties lexicographically.

    Used to pick a component's root from its candidate locations. The choice
    depends only on the set of paths, so it is stable regardless of iteration
    order.
    """

    ordered = sorted({path for path in paths if path}, key=sort_key_depth)

    return ordered[0] if ordered else None
