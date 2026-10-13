"""File classification.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Assigns each scanned file a category, language and format using only its
    name, path and extension - never its contents. Rules are applied in a fixed
    precedence order and the winning rule is recorded, so every classification
    can be audited and a consumer can tell a convention from a guess.
"""

from fnmatch import fnmatchcase
from pathlib import Path

from app.components.architecture_recovery.repository_inventory.catalog import (
    FILE_NAME_RULES,
    FORMAT_BY_EXTENSION,
    GENERIC_CONFIG_FORMATS,
    INFERRED_PATH_PATTERNS,
    LANGUAGE_BY_EXTENSION,
    PATH_SEGMENT_CATEGORIES,
    FileNameRule,
)
from app.components.architecture_recovery.repository_inventory.models import (
    Classification,
    Confidence,
    FileCategory,
    FileRecord,
)

# Formats that are documentation rather than configuration.
_DOCUMENTATION_FORMATS = frozenset({"markdown", "mdx", "rst", "asciidoc"})


class FileClassifier:
    """Classifies files from their name, path and extension.

    Every rule table is injectable, so supporting a new language or convention
    is a data change and a caller can override the tables without subclassing.
    """

    def __init__(
        self,
        file_name_rules: tuple[FileNameRule, ...] = FILE_NAME_RULES,
        path_segment_categories: dict[str, FileCategory] = PATH_SEGMENT_CATEGORIES,
        inferred_path_patterns: tuple[
            tuple[str, FileCategory], ...
        ] = INFERRED_PATH_PATTERNS,
        language_by_extension: dict[str, str] = LANGUAGE_BY_EXTENSION,
        format_by_extension: dict[str, str] = FORMAT_BY_EXTENSION,
    ) -> None:
        """Store the rule tables used for classification."""

        self._file_name_rules = file_name_rules
        self._path_segment_categories = path_segment_categories
        self._inferred_path_patterns = inferred_path_patterns
        self._language_by_extension = language_by_extension
        self._format_by_extension = format_by_extension

    def classify(self, file: FileRecord) -> Classification:
        """Classify `file`, filling in its language, format and category.

        Returns the classification record describing how the category was
        derived.
        """

        self._apply_extension(file)

        classification = (
            self._from_file_name(file)
            # Strong directory conventions (tests/, docs/, migrations/) beat the
            # extension, because `tests/helper.py` is a test, not source code.
            or self._from_path_segment(file, self._path_segment_categories)
            or self._from_language(file)
            # Weak conventions are only consulted once the file is known not to
            # be source code, so a .go file under deploy/ stays source code.
            or self._from_inferred_path(file)
            or self._from_format(file)
        )

        file.category = classification.category
        return classification

    def _apply_extension(self, file: FileRecord) -> None:
        """Fill language and format from the extension when not already known."""

        if file.extension:
            if file.language is None:
                file.language = self._language_by_extension.get(file.extension)
            if file.format is None:
                file.format = self._format_by_extension.get(file.extension)

    def _from_file_name(self, file: FileRecord) -> Classification | None:
        """Match the file name against the ordered filename rules."""

        name = file.name.lower()

        for rule in self._file_name_rules:
            if not fnmatchcase(name, rule.pattern):
                continue

            # A rule may add detail the extension alone cannot express, such as
            # the language of a `.proto` or the format of a `Dockerfile`.
            if rule.language and file.language is None:
                file.language = rule.language
            if rule.format and file.format is None:
                file.format = rule.format

            return Classification(
                file_id=file.id,
                category=rule.category,
                confidence=rule.confidence,
                rule=f"filename:{rule.pattern}",
            )

        return None

    def _from_path_segment(
        self, file: FileRecord, table: dict[str, FileCategory]
    ) -> Classification | None:
        """Match any directory segment of the path against the given table.

        Segments are examined from the deepest upwards so the directory closest
        to the file wins.
        """

        segments = Path(file.path).parts[:-1]

        for segment in reversed(segments):
            category = table.get(segment.lower())

            if category is not None:
                return Classification(
                    file_id=file.id,
                    category=category,
                    # Directory placement is a convention, not proof.
                    confidence=Confidence.INFERRED,
                    rule=f"path:{segment}",
                )

        return None

    def _from_inferred_path(self, file: FileRecord) -> Classification | None:
        """Match directory names against the weak deployment conventions.

        Names are matched as substrings, so `kubernetes-manifests/`, `k8s/` and
        `helm/charts/` all qualify.
        """

        segments = Path(file.path).parts[:-1]

        for segment in reversed(segments):
            lowered = segment.lower()

            for token, category in self._inferred_path_patterns:
                if token in lowered:
                    return Classification(
                        file_id=file.id,
                        category=category,
                        confidence=Confidence.INFERRED,
                        rule=f"path~:{segment}",
                    )

        return None

    def _from_language(self, file: FileRecord) -> Classification | None:
        """Treat a file with a known programming language as source code."""

        if file.language is None:
            return None

        return Classification(
            file_id=file.id,
            category=FileCategory.SOURCE_CODE,
            confidence=Confidence.CONFIRMED,
            rule=f"extension:{file.extension}",
        )

    def _from_format(self, file: FileRecord) -> Classification | None:
        """Fall back to a format-based category for unrecognised files."""

        if file.format in _DOCUMENTATION_FORMATS:
            category = FileCategory.DOCUMENTATION
        elif file.format in GENERIC_CONFIG_FORMATS:
            # A bare .json/.yaml is most likely configuration, but it could be
            # application data, so this is reported as inferred.
            category = FileCategory.INFRASTRUCTURE_CONFIG
        else:
            category = FileCategory.UNKNOWN

        return Classification(
            file_id=file.id,
            category=category,
            confidence=Confidence.INFERRED,
            rule=f"format:{file.format}" if file.format else "unclassified",
        )
