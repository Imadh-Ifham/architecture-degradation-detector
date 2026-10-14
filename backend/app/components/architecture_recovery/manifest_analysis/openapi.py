"""OpenAPI and AsyncAPI specification analyzer.

Author: Imadh Ifham
Date: 2026-10-14
Description:
    Parses OpenAPI/Swagger/AsyncAPI documents into the API they describe, the
    servers they declare as base urls, and the operations they define.

    Every finding here is an API *definition*: a path existing in a
    specification says nothing about whether any service implements it or calls
    it, so nothing is recorded as a dependency.
"""

import json
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from app.components.architecture_recovery.manifest_analysis.base import (
    AnalyzerResult,
    ManifestAnalyzer,
    has_template_expressions,
    read_manifest_text,
)
from app.components.architecture_recovery.manifest_analysis.models import (
    DeclaredRelationship,
    DeclaredResource,
    DiagnosticSeverity,
    Endpoint,
    ExtractedEvidence,
    ExtractionMethod,
    ParseStatus,
    RelationshipOrigin,
    RelationshipType,
    ResourceKind,
    SourceLocation,
    endpoint_id,
    relationship_id,
    resource_id,
)
from app.components.architecture_recovery.manifest_analysis.redaction import (
    extract_endpoint_candidate,
)
from app.components.architecture_recovery.manifest_analysis.yaml_support import (
    load_yaml_documents,
    line_of,
)
from app.components.architecture_recovery.repository_inventory.models import (
    FileRecord,
)

SPECIFICATION_NAME_PATTERNS: tuple[str, ...] = (
    "openapi*.json",
    "openapi*.yaml",
    "openapi*.yml",
    "swagger*.json",
    "swagger*.yaml",
    "swagger*.yml",
    "asyncapi*.json",
    "asyncapi*.yaml",
    "asyncapi*.yml",
    "*.openapi.json",
    "*.openapi.yaml",
    "*.openapi.yml",
)

# Keys whose presence identifies the document as an API specification.
_SPECIFICATION_KEYS = ("openapi", "swagger", "asyncapi")

# HTTP methods that can appear under a path item. Anything else there is a
# path-level property such as `parameters` or `servers`.
_HTTP_METHODS = frozenset(
    {
        "get",
        "put",
        "post",
        "delete",
        "options",
        "head",
        "patch",
        "trace",
        "subscribe",
        "publish",
    }
)

_MAX_SUMMARY_LENGTH = 300


class OpenApiAnalyzer(ManifestAnalyzer):
    """Analyzes an OpenAPI, Swagger or AsyncAPI specification."""

    name = "openapi"

    def __init__(self, max_bytes: int = 1_048_576) -> None:
        """Store the maximum number of bytes read from a single file."""

        self._max_bytes = max_bytes

    def can_analyze(self, file: FileRecord) -> bool:
        """Match a specification by filename convention on json or yaml."""

        if file.format not in ("json", "yaml"):
            return False

        name = file.name.lower()

        return any(
            fnmatchcase(name, pattern) for pattern in SPECIFICATION_NAME_PATTERNS
        )

    def analyze(self, file: FileRecord, absolute_path: Path) -> AnalyzerResult:
        """Extract the API, its servers and its operations."""

        result = AnalyzerResult(
            method=ExtractionMethod.JSON
            if file.format == "json"
            else ExtractionMethod.YAML
        )

        text, diagnostic = read_manifest_text(
            absolute_path, self._max_bytes, file.path
        )

        if text is None:
            result.status = ParseStatus.SKIPPED
            result.diagnostics.append(diagnostic)
            return result

        if has_template_expressions(text):
            result.status = ParseStatus.SKIPPED
            result.add_diagnostic(
                DiagnosticSeverity.WARNING,
                "templated specification cannot be parsed without resolving its "
                "template expressions",
                file.path,
                None,
                self.name,
            )
            return result

        document, positions, error, error_line = _parse(text, file.format)

        if error is not None:
            result.status = ParseStatus.FAILED
            result.add_diagnostic(
                DiagnosticSeverity.ERROR,
                f"could not parse specification: {error}",
                file.path,
                error_line,
                self.name,
            )
            return result

        if document is None:
            result.status = ParseStatus.FAILED
            result.add_diagnostic(
                DiagnosticSeverity.ERROR,
                "specification is not a mapping document",
                file.path,
                None,
                self.name,
            )
            return result

        if not any(key in document for key in _SPECIFICATION_KEYS):
            # The filename promised a specification but the content does not
            # look like one. Recorded rather than guessed at.
            result.status = ParseStatus.PARTIAL
            result.add_diagnostic(
                DiagnosticSeverity.WARNING,
                "document has none of the "
                f"{', '.join(_SPECIFICATION_KEYS)} keys; not treated as a specification",
                file.path,
                None,
                self.name,
            )
            return result

        analysis = _SpecificationAnalysis(file, result, positions)
        analysis.run(document)

        if not result.resources:
            result.status = ParseStatus.PARTIAL

        return result


def _parse(
    text: str, file_format: str | None
) -> tuple[Any, dict[int, int], str | None, int | None]:
    """Parse a specification once, returning the document and its positions.

    A single parse means the position table always describes the document that
    was actually analysed. JSON has no position information available here, so
    its table is empty and lines are reported as unknown rather than guessed at.
    """

    if file_format == "json":
        try:
            return json.loads(text), {}, None, None
        except json.JSONDecodeError as error:
            return None, {}, error.msg, error.lineno

    loaded = load_yaml_documents(text)

    if loaded.error:
        return None, loaded.positions, loaded.error, loaded.error_line

    document = next(
        (item.data for item in loaded.documents if isinstance(item.data, dict)), None
    )

    return document, loaded.positions, None, None


class _SpecificationAnalysis:
    """Walks one specification document and records its API surface."""

    #: Analyzer name used on diagnostics raised from within this helper.
    _ANALYZER_NAME = "openapi"

    def __init__(self, file: FileRecord, result: AnalyzerResult, positions: dict) -> None:
        """Bind the analysis to a file, its result and the position table."""

        self._file = file
        self._result = result
        self._positions = positions
        self._api_id: str | None = None

    def run(self, document: dict) -> None:
        """Record the API, its servers and its operations."""

        self._record_api(document)
        self._record_servers(document)
        self._record_paths(document)

    def _record_api(self, document: dict) -> None:
        """Record the API itself, named by its title."""

        info = document.get("info")
        info = info if isinstance(info, dict) else {}

        title = _text(info.get("title")) or self._file.name
        version = _text(info.get("version"))

        specification_version = None

        for key in _SPECIFICATION_KEYS:
            if document.get(key) is not None:
                specification_version = f"{key} {document[key]}"
                break

        location = self._location(document)

        attributes: dict = {
            "version": version,
            "specification": specification_version,
        }

        if self._file.component_id:
            # Ties the API to the candidate component the inventory associated
            # with this file.
            attributes["component_id"] = self._file.component_id

        self._api_id = resource_id(self._file.path, ResourceKind.API, title)

        self._result.resources.append(
            DeclaredResource(
                id=self._api_id,
                kind=ResourceKind.API,
                name=title,
                location=location,
                analyzer="openapi",
                method=self._result.method,
                attributes=attributes,
                evidence=[
                    ExtractedEvidence(
                        "openapi_info",
                        f"API '{title}'"
                        + (f" version {version}" if version else "")
                        + " is declared",
                        self._result.method,
                        location,
                    )
                ],
            )
        )

    def _record_servers(self, document: dict) -> None:
        """Record each declared server as a configured endpoint."""

        if self._api_id is None:
            return

        for server in document.get("servers") or []:
            if not isinstance(server, dict):
                continue

            url = _text(server.get("url"))

            if not url:
                continue

            location = self._location(server)

            # A specification url may be a template such as
            # `https://{host}/api`, which cannot be resolved to a real host.
            templated = "{" in url
            candidate = None if templated else extract_endpoint_candidate(url)

            endpoint = Endpoint(
                id=endpoint_id(self._file.path, f"server:{url}"),
                location=location,
                host=candidate.host if candidate else None,
                port=candidate.port if candidate else None,
                protocol=candidate.scheme if candidate else None,
                source_resource_id=self._api_id,
                scope="base_url",
                evidence=[
                    ExtractedEvidence(
                        "openapi_server",
                        f"server url '{url}' is declared"
                        + (" (templated, host unresolved)" if templated else ""),
                        self._result.method,
                        location,
                    )
                ],
            )

            self._result.endpoints.append(endpoint)

            self._add_relationship(
                RelationshipType.SERVES_AT,
                RelationshipOrigin.CONFIGURED_ENDPOINT,
                self._api_id,
                endpoint.id,
                location,
                not templated,
                f"API is served at '{url}'",
            )

            if templated:
                self._result.add_diagnostic(
                    DiagnosticSeverity.INFO,
                    f"server url '{url}' is templated; its host is unresolved",
                    self._file.path,
                    location.line,
                    self._ANALYZER_NAME,
                )

    def _record_paths(self, document: dict) -> None:
        """Record one operation resource per path and method."""

        if self._api_id is None:
            return

        paths = document.get("paths")

        if not isinstance(paths, dict):
            return

        for path, item in paths.items():
            if not isinstance(item, dict):
                continue

            for method, operation in item.items():
                if method.lower() not in _HTTP_METHODS:
                    continue

                operation_data = operation if isinstance(operation, dict) else {}
                operation_id = _text(operation_data.get("operationId"))
                name = operation_id or f"{method.upper()} {path}"

                location = self._location(operation_data or item)

                attributes: dict = {
                    "method": method.upper(),
                    "path": str(path),
                    "operation_id": operation_id,
                }

                tags = operation_data.get("tags")

                if isinstance(tags, list) and tags:
                    attributes["tags"] = [str(tag) for tag in tags]

                summary = _text(operation_data.get("summary"))

                if summary:
                    attributes["summary"] = summary[:_MAX_SUMMARY_LENGTH]

                if "deprecated" in operation_data:
                    attributes["deprecated"] = bool(operation_data["deprecated"])

                identifier = resource_id(
                    self._file.path,
                    ResourceKind.API_OPERATION,
                    f"{method.upper()} {path}",
                )

                self._result.resources.append(
                    DeclaredResource(
                        id=identifier,
                        kind=ResourceKind.API_OPERATION,
                        name=name,
                        location=location,
                        analyzer="openapi",
                        method=self._result.method,
                        attributes=attributes,
                        evidence=[
                            ExtractedEvidence(
                                "openapi_operation",
                                f"{method.upper()} {path} is defined"
                                + (f" as '{operation_id}'" if operation_id else ""),
                                self._result.method,
                                location,
                            )
                        ],
                    )
                )

                self._add_relationship(
                    RelationshipType.DEFINES_OPERATION,
                    RelationshipOrigin.API_DEFINITION,
                    self._api_id,
                    identifier,
                    location,
                    True,
                    f"the API defines {method.upper()} {path}",
                )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _location(self, node: Any) -> SourceLocation:
        """Build a source location for a parsed node."""

        return SourceLocation(
            path=self._file.path, line=line_of(node, self._positions)
        )

    def _add_relationship(
        self,
        relationship_type: RelationshipType,
        origin: RelationshipOrigin,
        source_id: str,
        target_id: str,
        location: SourceLocation,
        resolved: bool,
        detail: str,
    ) -> None:
        """Record a relationship with its evidence."""

        self._result.relationships.append(
            DeclaredRelationship(
                id=relationship_id(relationship_type, source_id, target_id),
                type=relationship_type,
                origin=origin,
                source_id=source_id,
                target_id=target_id,
                location=location,
                resolved=resolved,
                evidence=[
                    ExtractedEvidence(
                        "openapi_declaration",
                        detail,
                        self._result.method,
                        location,
                    )
                ],
            )
        )


def _text(value: Any) -> str | None:
    """Return a non-empty string for a scalar, else None."""

    if value is None:
        return None

    text = str(value).strip()

    return text or None
