"""Prompts, as files.

Author: Aman Mohamed M.A
Date: 2026-10-16
Description:
    Loads a versioned prompt off disk into the shape a component is handed.

    The prompts live here, beside the provider adapters, rather than inside
    the component that uses one. One folder for every prompt in the project,
    one loader, and the versioning then applies to a teammate's prompt without
    them writing any of it.

    A prompt is a file for the same reason a migration is: an inline string
    cannot be diffed, cannot be reviewed by a supervisor, and makes the
    paraphrase-robustness arm of the study a code change rather than a second
    file.

    The version is taken from the file name rather than from anything inside
    it. A version a writer has to remember to update is a version that
    eventually describes the wrong text - and this one is part of the cache
    key, so a stale one would serve yesterday's answer to today's prompt.
"""

import re
from pathlib import Path

from app.components.architecture_validation.models import PromptTemplate

PROMPT_DIRECTORY = Path(__file__).parent / "prompts"

SYSTEM_FENCE = "--- system ---"
USER_FENCE = "--- user ---"

_FILENAME = re.compile(r"^(?P<name>[a-z0-9_]+)\.v(?P<version>\d+)\.md$")


class PromptFileError(ValueError):
    """A prompt file is missing or does not have the two sections.

    Raised rather than returning what could be read. A prompt with its rules
    silently missing still produces fluent answers, and nothing downstream
    would report that the model was never told what to do.
    """


def load_prompt(file_name: str, directory: Path | str | None = None) -> PromptTemplate:
    """Load one prompt file into a template.

    Called by the composition root at start-up, once, and the template handed
    to the subcomponent that needs it.
    """

    root = Path(directory) if directory is not None else PROMPT_DIRECTORY
    matched = _FILENAME.match(file_name)
    if matched is None:
        raise PromptFileError(
            f"'{file_name}' is not a prompt file name. Expected "
            "<name>.v<number>.md, for example primary_verdict.v1.md, because "
            "the version is read from the name."
        )

    path = root / file_name
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise PromptFileError(
            f"Could not read the prompt file {path}: {error}"
        ) from error

    return PromptTemplate(
        version=f"{matched['name']}@{matched['version']}",
        system=_section(text, SYSTEM_FENCE, USER_FENCE, path),
        body=_section(text, USER_FENCE, None, path),
    )


def _section(text: str, opening: str, closing: str | None, path: Path) -> str:
    """The text between one fence and the next, or the end of the file."""

    if opening not in text:
        raise PromptFileError(f"{path} has no '{opening}' section.")

    after = text.split(opening, 1)[1]
    if closing is not None:
        after = after.split(closing, 1)[0]

    section = after.strip()
    if not section:
        raise PromptFileError(f"The '{opening}' section of {path} is empty.")
    return section


__all__ = ["PROMPT_DIRECTORY", "PromptFileError", "load_prompt"]
