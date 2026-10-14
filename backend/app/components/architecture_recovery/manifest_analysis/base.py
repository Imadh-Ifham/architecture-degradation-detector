"""Analyzer interface and shared helpers.

Author: Imadh Ifham
Date: 2026-10-14
Description:
    Defines the contract every manifest analyzer implements, plus the working
    container analyzers fill in and the bounded text read they share.

    Analyzers are deliberately independent of the inventory: they receive one
    `FileRecord` (already classified by the inventory) and the absolute path of
    that file, and they return structured findings. Selection between analyzers
    is the registry's job, and repository traversal is nobody's job here.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from app.components.architecture_recovery.manifest_analysis.models import (
    DeclaredRelationship,
    DeclaredResource,
    Diagnostic,
    DiagnosticSeverity,
    Endpoint,
    ExtractionMethod,
    FileAnalysisResult,
    ParseStatus,
    ResourceReference,
)
from app.components.architecture_recovery.repository_inventory.models import (
    FileRecord,
)


# `{{ ... }}` (Helm, Jinja) and `{% ... %}` are template expressions, which
# cannot be resolved without the templating engine that renders them.
_TEMPLATE_EXPRESSION = re.compile(r"\{\{|\{%")


def has_template_expressions(text: str) -> bool:
    """Report whether a manifest contains template expressions.

    Such a file is not malformed, so it is reported as skipped rather than
    failed: parsing it would require rendering the template first, which this
    stage deliberately does not do.
    """

    return bool(_TEMPLATE_EXPRESSION.search(text))


def read_manifest_text(
    path: Path, max_bytes: int, display_path: str
) -> tuple[str | None, Diagnostic | None]:
    """Read a manifest as text, bounded by `max_bytes`.

    Returns the text and no diagnostic on success, or `None` and the diagnostic
    explaining why the file was not read. Never raises for a filesystem problem.
    """

    try:
        with path.open("rb") as handle:
            raw = handle.read(max_bytes + 1)
    except OSError as error:
        return None, Diagnostic(
            severity=DiagnosticSeverity.ERROR,
            message=f"could not read file: {error}",
            path=display_path,
        )

    if len(raw) > max_bytes:
        return None, Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            message=f"skipped: file exceeds the {max_bytes} byte analysis limit",
            path=display_path,
        )

    # Manifests are text formats; a replacement character is preferable to
    # failing the whole file on one bad byte.
    return raw.decode("utf-8", errors="replace"), None


@dataclass
class AnalyzerResult:
    """The findings one analyzer produced for one file."""

    status: ParseStatus = ParseStatus.PARSED
    method: ExtractionMethod | None = None
    resources: list[DeclaredResource] = field(default_factory=list)
    relationships: list[DeclaredRelationship] = field(default_factory=list)
    endpoints: list[Endpoint] = field(default_factory=list)
    references: list[ResourceReference] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def add_diagnostic(
        self,
        severity: DiagnosticSeverity,
        message: str,
        path: str,
        line: int | None = None,
        analyzer: str | None = None,
    ) -> None:
        """Record a diagnostic on this result."""

        self.diagnostics.append(
            Diagnostic(
                severity=severity,
                message=message,
                path=path,
                line=line,
                analyzer=analyzer,
            )
        )

    def has_errors(self) -> bool:
        """Report whether any recorded diagnostic is an error."""

        return any(
            item.severity is DiagnosticSeverity.ERROR for item in self.diagnostics
        )

    def to_file_result(self, path: str, analyzer: str | None) -> FileAnalysisResult:
        """Project the findings into the per-file result stored on the report.

        The path is supplied by the caller rather than inferred, because a file
        that produced no findings still has to be reported against its own path.
        """

        return FileAnalysisResult(
            path=path,
            analyzer=analyzer,
            status=self.status,
            method=self.method,
            resource_ids=[item.id for item in self.resources],
            relationship_ids=[item.id for item in self.relationships],
            diagnostics=self.diagnostics,
        )


class ManifestAnalyzer(ABC):
    """Base class for a format-specific manifest analyzer."""

    #: Short stable name used in diagnostics and in the report's summary.
    name: str = "analyzer"

    @abstractmethod
    def can_analyze(self, file: FileRecord) -> bool:
        """Report whether this analyzer handles the given inventory file.

        This refines *which analyzer* handles an already-relevant file; the
        inventory has already decided that the file is a manifest at all.
        """

    @abstractmethod
    def analyze(self, file: FileRecord, absolute_path: Path) -> AnalyzerResult:
        """Extract structured findings from one manifest file.

        Implementations must not raise for malformed input: a parse failure is
        a diagnostic on the result, never an exception.
        """
