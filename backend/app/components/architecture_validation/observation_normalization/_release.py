"""Release identifier ordering.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    Turns a release identifier into something that orders, or refuses it.

    `"v0.10.0" > "v0.9.0"` is False. Compared as text the third character
    decides it - `'1' < '9'` - so the newer release sorts first, with no
    exception and no log line. The decision knowledge model places a fact's
    release inside a half-open validity interval, so an ordering that runs
    backwards means a superseded decision governs a release it was replaced
    before. That is the one claim this component rests on, wrong, silently, on
    exactly the release pair the demonstration is built from.

    So every fact carries a sort key alongside the original string, and an
    identifier that cannot be ordered stops the run. There is deliberately no
    lexicographic fallback: a plausible wrong order is worse than a stop,
    because a stop is visible and a wrong order is not.

    This happens in M1 because M1 is the boundary every fact crosses. Parsing
    in M2 as well would mean two parsers that can disagree with each other.
"""

from functools import lru_cache

from packaging.version import InvalidVersion, Version

RELEASE_SEGMENTS = 4
"""How many numeric segments the sort key carries.

Fixed rather than variable, because the key has a tail after the segments and
a variable-length prefix would compare a segment against that tail. Four is
one more than the three of semantic versioning, so `1.2.3.4` still orders; an
identifier with more segments than this is refused rather than ordered by the
first four of them.
"""

_PRE_RANKS = {"a": 1, "b": 2, "rc": 3}
"""Pre-release letters, weakest first. Normalised by `Version`, so `alpha`
arrives as `a` and `c` as `rc` and this table does not need their spellings."""


class UnorderableRelease(ValueError):
    """A release identifier that cannot be placed in order.

    Raised rather than worked around. A date stamp, a build label or
    `release-2024-Q3` describes a release perfectly well but says nothing
    about which of two came first, and this component's temporal claim cannot
    be evaluated on a repository whose releases do not order.
    """


@lru_cache(maxsize=256)
def release_sort_key(release_id: str) -> tuple[int, ...]:
    """Return a tuple that orders `release_id` against other releases.

    Cached because one run asks for the same one or two identifiers once per
    fact, and the answer cannot change for a given string. A refusal is not
    cached and is raised every time, which is what keeps it from being parsed
    once and then forgotten.
    """

    version = _parse(release_id)
    segments = tuple(version.release)
    padding = (0,) * (RELEASE_SEGMENTS - len(segments))

    return (version.epoch, *segments, *padding, *_variant_key(version))


def _parse(release_id: str) -> Version:
    """Read one release identifier, or say why it cannot be read."""

    candidate = release_id.strip()
    if candidate[:1] in ("v", "V"):
        # Tags are written `v0.10.0` far more often than `0.10.0`. One leading
        # `v` is stripped, and only one: `vv1.0` is a typo, not a release.
        candidate = candidate[1:]

    try:
        version = Version(candidate)
    except InvalidVersion as error:
        raise UnorderableRelease(
            f"release identifier {release_id!r} cannot be ordered: it is not a "
            "version number. Name the release by a version tag, because the "
            "validity intervals in the decision history compare releases to "
            "each other."
        ) from error

    if len(version.release) > RELEASE_SEGMENTS:
        raise UnorderableRelease(
            f"release identifier {release_id!r} cannot be ordered: it has "
            f"{len(version.release)} numeric segments and the sort key carries "
            f"{RELEASE_SEGMENTS}. Ordering by the first {RELEASE_SEGMENTS} "
            "would make two different releases compare equal."
        )

    return version


def _variant_key(version: Version) -> tuple[int, int, int, int]:
    """Where this identifier sits among variants of the same release.

    PEP 440 orders them `1.0.dev1 < 1.0a1 < 1.0b1 < 1.0rc1 < 1.0 < 1.0.post1`,
    and the stage number below is that sequence. A development release of a
    variant sits below the variant itself, which is why the development marker
    is a separate pair rather than part of the stage: `1.0rc1.dev1` is still an
    `rc1`, just not finished being one.
    """

    if version.pre is not None:
        stage, ordinal = _PRE_RANKS[version.pre[0]], version.pre[1]
    elif version.post is not None:
        stage, ordinal = 5, version.post
    elif version.dev is not None:
        stage, ordinal = 0, 0
    else:
        stage, ordinal = 4, 0

    return (stage, ordinal, 0 if version.dev is not None else 1, version.dev or 0)


__all__ = ["RELEASE_SEGMENTS", "UnorderableRelease", "release_sort_key"]
