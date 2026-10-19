"""Prompt loading tests.

Author: Aman Mohamed M.A
Date: 2026-10-16
Description:
    A prompt is a file so that it can be reviewed and diffed, and so that a
    changed prompt is a new version rather than an edit. That only holds if
    the version travels with the text and the loader refuses a file it cannot
    read properly.

    The failure this guards against is quiet. A prompt whose rules section is
    missing still produces fluent, well-shaped answers - the model was simply
    never told what the rules were, and no stage downstream can tell.
"""

from pathlib import Path

import pytest

from app.infrastructure.ai.prompt_library import (
    PROMPT_DIRECTORY,
    PromptFileError,
    load_prompt,
)

PRIMARY = "primary_verdict.v1.md"


class TestLoadingTheRealPrompt:
    """The file the reasoner is actually given."""

    def test_the_version_comes_from_the_file_name(self):
        """Not from anything inside the file. A version somebody has to
        remember to update eventually describes the wrong text, and this one
        is part of the cache key - so a stale version serves yesterday's
        answer to today's prompt."""

        assert load_prompt(PRIMARY).version == "primary_verdict@1"

    def test_the_two_sections_are_split_and_neither_leaks_into_the_other(self):
        template = load_prompt(PRIMARY)

        assert "verdict is one of" in template.system
        assert "What is the verdict?" in template.body
        assert "--- user ---" not in template.system
        assert "verdict is one of" not in template.body

    def test_the_rules_say_what_the_labels_mean(self):
        """The package's roles are the one thing a schema cannot convey. A
        prompt that does not explain `superseded` invites a verdict resting on
        the decision the resolver rejected."""

        system = load_prompt(PRIMARY).system

        for role in ("rule", "superseded", "permitted_set", "structural_context"):
            assert role in system

    @pytest.mark.parametrize(
        "name", sorted(path.name for path in PROMPT_DIRECTORY.glob("*.md"))
    )
    def test_every_prompt_in_the_folder_loads(self, name):
        """One folder for every prompt in the project, so a teammate's file is
        held to the same shape without them writing a test for it."""

        assert load_prompt(name).system


class TestWhenAFileCannotBeTrusted:
    """Each of these would otherwise reach a model as a partial prompt."""

    def test_a_name_with_no_version_is_refused(self):
        with pytest.raises(PromptFileError, match="not a prompt file name"):
            load_prompt("primary_verdict.md")

    def test_a_missing_file_is_refused(self):
        with pytest.raises(PromptFileError, match="Could not read"):
            load_prompt("not_written_yet.v1.md")

    def test_a_file_with_no_rules_section_is_refused(self, tmp_path: Path):
        (tmp_path / "half.v1.md").write_text(
            "--- user ---\nJudge it.\n", encoding="utf-8"
        )

        with pytest.raises(PromptFileError, match="system"):
            load_prompt("half.v1.md", tmp_path)

    def test_a_file_with_no_question_section_is_refused(self, tmp_path: Path):
        (tmp_path / "half.v1.md").write_text(
            "--- system ---\nRules.\n", encoding="utf-8"
        )

        with pytest.raises(PromptFileError, match="user"):
            load_prompt("half.v1.md", tmp_path)

    def test_an_empty_section_is_refused(self, tmp_path: Path):
        (tmp_path / "empty.v1.md").write_text(
            "--- system ---\n\n--- user ---\nJudge it.\n", encoding="utf-8"
        )

        with pytest.raises(PromptFileError, match="is empty"):
            load_prompt("empty.v1.md", tmp_path)
