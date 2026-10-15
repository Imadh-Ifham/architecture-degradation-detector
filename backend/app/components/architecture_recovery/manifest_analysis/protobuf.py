"""Protobuf service definition analyzer.

Author: Imadh Ifham
Date: 2026-10-14
Description:
    Parses `.proto` files into their package, services, RPC methods and message
    types, together with the request and response types each method uses.

    This is a declaration-level parser: it reads the source rather than compiled
    descriptors, so comments and whitespace are handled but full protobuf
    semantics (options, imports, nested scopes) are not interpreted. Imports and
    message types declared in another file are recorded as unresolved references
    for a later resolution stage.
"""

import re
from pathlib import Path

from app.components.architecture_recovery.manifest_analysis.base import (
    AnalyzerResult,
    ManifestAnalyzer,
    read_manifest_text,
)
from app.components.architecture_recovery.manifest_analysis.models import (
    DeclaredRelationship,
    DeclaredResource,
    DiagnosticSeverity,
    ExtractedEvidence,
    ExtractionMethod,
    ParseStatus,
    ReferenceKind,
    ReferenceStatus,
    RelationshipOrigin,
    RelationshipType,
    ResourceKind,
    ResourceReference,
    SourceLocation,
    reference_id,
    relationship_id,
    resource_id,
)
from app.components.architecture_recovery.repository_inventory.models import (
    FileRecord,
)

_PACKAGE_PATTERN = re.compile(r"^\s*package\s+(?P<name>[A-Za-z_][\w.]*)\s*;")
_SERVICE_PATTERN = re.compile(r"^\s*service\s+(?P<name>\w+)\s*\{")
_MESSAGE_PATTERN = re.compile(r"^\s*message\s+(?P<name>\w+)\s*\{")
_ENUM_PATTERN = re.compile(r"^\s*enum\s+(?P<name>\w+)\s*\{")
_IMPORT_PATTERN = re.compile(r'^\s*import\s+(?:public\s+|weak\s+)?"(?P<path>[^"]+)"\s*;')
# `rpc Name (stream Request) returns (stream Response)`
_RPC_PATTERN = re.compile(
    r"^\s*rpc\s+(?P<name>\w+)\s*"
    r"\(\s*(?:stream\s+)?(?P<request>[\w.]+)\s*\)\s*"
    r"returns\s*\(\s*(?:stream\s+)?(?P<response>[\w.]+)\s*\)",
)

_SYNTAX_PATTERN = re.compile(r'^\s*syntax\s*=\s*"(?P<syntax>[^"]+)"\s*;')

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


class ProtobufAnalyzer(ManifestAnalyzer):
    """Analyzes a `.proto` service definition file."""

    name = "protobuf"

    def __init__(self, max_bytes: int = 1_048_576) -> None:
        """Store the maximum number of bytes read from a single file."""

        self._max_bytes = max_bytes

    def can_analyze(self, file: FileRecord) -> bool:
        """Match by the `.proto` extension, which is unambiguous."""

        return file.extension == ".proto"

    def analyze(self, file: FileRecord, absolute_path: Path) -> AnalyzerResult:
        """Extract the package, services, RPCs and messages."""

        result = AnalyzerResult(method=ExtractionMethod.PROTOBUF)

        text, diagnostic = read_manifest_text(
            absolute_path, self._max_bytes, file.path
        )

        if text is None:
            result.status = ParseStatus.SKIPPED
            result.diagnostics.append(diagnostic)
            return result

        analysis = _ProtobufAnalysis(file, result)
        analysis.run(text)

        if not result.resources:
            result.status = ParseStatus.PARTIAL
            result.add_diagnostic(
                DiagnosticSeverity.WARNING,
                "no package, service or message declaration found",
                file.path,
                None,
                self.name,
            )

        return result


def _strip_comments(text: str) -> str:
    """Remove block and line comments while preserving line numbering."""

    # Block comments are blanked rather than removed so subsequent line numbers
    # still line up with the original file.
    text = _BLOCK_COMMENT.sub(
        lambda match: "\n" * match.group(0).count("\n"), text
    )

    lines = []

    for line in text.splitlines():
        stripped = line.lstrip()

        if stripped.startswith("//"):
            lines.append("")
            continue

        # A trailing comment is dropped, but a `//` inside a string literal is
        # rare enough in a .proto file to accept this simplification.
        marker = line.find("//")

        lines.append(line[:marker] if marker != -1 else line)

    return "\n".join(lines)


class _ProtobufAnalysis:
    """Walks one `.proto` file and records its declarations."""

    def __init__(self, file: FileRecord, result: AnalyzerResult) -> None:
        """Bind the analysis to a file and its result."""

        self._file = file
        self._result = result

        self._messages: dict[str, str] = {}
        self._services: dict[str, str] = {}
        self._package_id: str | None = None
        self._current_service: str | None = None
        self._service_depth = 0
        self._depth = 0

    def run(self, text: str) -> None:
        """Process the file line by line, tracking brace depth for scope."""

        cleaned = _strip_comments(text)

        for line_number, line in enumerate(cleaned.splitlines(), start=1):
            location = SourceLocation(path=self._file.path, line=line_number)

            self._record_syntax(line, location)
            self._record_package(line, location)
            self._record_import(line, location)

            if self._messages_declaration(line):
                self._record_message(line, location)

            self._record_service_open(line, location)
            self._record_rpc(line, location)

            self._track_depth(line)

    # ------------------------------------------------------------------ #
    # Declarations
    # ------------------------------------------------------------------ #

    def _record_syntax(self, line: str, location: SourceLocation) -> None:
        """Record the declared syntax version as file-level context."""

        match = _SYNTAX_PATTERN.match(line)

        if match and self._package_id is None:
            self._syntax = match.group("syntax")

    def _record_package(self, line: str, location: SourceLocation) -> None:
        """Record the proto package."""

        match = _PACKAGE_PATTERN.match(line)

        if not match:
            return

        name = match.group("name")
        identifier = resource_id(self._file.path, ResourceKind.PROTO_PACKAGE, name)
        self._package_id = identifier

        self._result.resources.append(
            DeclaredResource(
                id=identifier,
                kind=ResourceKind.PROTO_PACKAGE,
                name=name,
                location=location,
                analyzer="protobuf",
                method=ExtractionMethod.PROTOBUF,
                attributes={
                    "syntax": getattr(self, "_syntax", None),
                    **(
                        {"component_id": self._file.component_id}
                        if self._file.component_id
                        else {}
                    ),
                },
                evidence=[
                    ExtractedEvidence(
                        "protobuf_package",
                        f"package '{name}' is declared",
                        ExtractionMethod.PROTOBUF,
                        location,
                    )
                ],
            )
        )

    def _record_import(self, line: str, location: SourceLocation) -> None:
        """Record a file-level import as an unresolved reference."""

        match = _IMPORT_PATTERN.match(line)

        if not match:
            return

        imported = match.group("path")

        self._result.references.append(
            ResourceReference(
                id=reference_id(
                    self._file.path, ReferenceKind.FILE, imported, "protobuf_import"
                ),
                kind=ReferenceKind.FILE,
                name=imported,
                location=location,
                status=ReferenceStatus.UNRESOLVED,
                reference_type="protobuf_import",
                reason="imported definition lives in another file",
                evidence=[
                    ExtractedEvidence(
                        "protobuf_import",
                        f"'{imported}' is imported",
                        ExtractionMethod.PROTOBUF,
                        location,
                    )
                ],
            )
        )

    def _messages_declaration(self, line: str) -> bool:
        """Report whether the line opens a message or enum block."""

        return bool(_MESSAGE_PATTERN.match(line) or _ENUM_PATTERN.match(line))

    def _record_message(self, line: str, location: SourceLocation) -> None:
        """Record a message or enum declaration.

        Nested messages are recorded as flat declarations: the body is not
        scoped, which keeps the model simple without losing the type names.
        """

        match = _MESSAGE_PATTERN.match(line) or _ENUM_PATTERN.match(line)

        if not match:
            return

        name = match.group("name")

        if name in self._messages:
            return

        identifier = resource_id(self._file.path, ResourceKind.PROTO_MESSAGE, name)
        self._messages[name] = identifier

        self._result.resources.append(
            DeclaredResource(
                id=identifier,
                kind=ResourceKind.PROTO_MESSAGE,
                name=name,
                location=location,
                analyzer="protobuf",
                method=ExtractionMethod.PROTOBUF,
                attributes={
                    "package": self._package_name(),
                    "enum": bool(_ENUM_PATTERN.match(line)),
                },
                evidence=[
                    ExtractedEvidence(
                        "protobuf_message",
                        f"message type '{name}' is declared",
                        ExtractionMethod.PROTOBUF,
                        location,
                    )
                ],
            )
        )

    def _record_service_open(self, line: str, location: SourceLocation) -> bool:
        """Record a service declaration and enter its scope."""

        match = _SERVICE_PATTERN.match(line)

        if not match:
            return False

        name = match.group("name")
        identifier = resource_id(self._file.path, ResourceKind.PROTO_SERVICE, name)
        self._services[name] = identifier
        self._current_service = name
        self._service_depth = self._depth

        self._result.resources.append(
            DeclaredResource(
                id=identifier,
                kind=ResourceKind.PROTO_SERVICE,
                name=name,
                location=location,
                analyzer="protobuf",
                method=ExtractionMethod.PROTOBUF,
                attributes={
                    "package": self._package_name(),
                    **(
                        {"component_id": self._file.component_id}
                        if self._file.component_id
                        else {}
                    ),
                },
                evidence=[
                    ExtractedEvidence(
                        "protobuf_service",
                        f"service '{name}' is declared",
                        ExtractionMethod.PROTOBUF,
                        location,
                    )
                ],
            )
        )

        if self._package_id is not None:
            self._add_relationship(
                RelationshipType.DECLARES_PACKAGE,
                RelationshipOrigin.API_DEFINITION,
                identifier,
                self._package_id,
                location,
                True,
                f"service '{name}' is declared in package "
                f"'{self._package_name()}'",
            )

        return True

    def _record_rpc(self, line: str, location: SourceLocation) -> None:
        """Record an RPC method and the types it exchanges."""

        match = _RPC_PATTERN.match(line)

        if not match or self._current_service is None:
            return

        name = match.group("name")
        service_id = self._services[self._current_service]

        identifier = resource_id(
            self._file.path, ResourceKind.PROTO_RPC, f"{self._current_service}.{name}"
        )

        self._result.resources.append(
            DeclaredResource(
                id=identifier,
                kind=ResourceKind.PROTO_RPC,
                name=name,
                location=location,
                analyzer="protobuf",
                method=ExtractionMethod.PROTOBUF,
                attributes={
                    "service": self._current_service,
                    "request_type": match.group("request"),
                    "response_type": match.group("response"),
                },
                evidence=[
                    ExtractedEvidence(
                        "protobuf_rpc",
                        f"rpc '{name}' accepts '{match.group('request')}' and "
                        f"returns '{match.group('response')}'",
                        ExtractionMethod.PROTOBUF,
                        location,
                    )
                ],
            )
        )

        self._add_relationship(
            RelationshipType.DEFINES_RPC,
            RelationshipOrigin.API_DEFINITION,
            service_id,
            identifier,
            location,
            True,
            f"service '{self._current_service}' defines rpc '{name}'",
        )

        self._link_message_type(
            identifier,
            match.group("request"),
            RelationshipType.ACCEPTS_MESSAGE,
            "request",
            location,
        )
        self._link_message_type(
            identifier,
            match.group("response"),
            RelationshipType.RETURNS_MESSAGE,
            "response",
            location,
        )

    def _link_message_type(
        self,
        rpc_id: str,
        type_name: str,
        relationship_type: RelationshipType,
        role: str,
        location: SourceLocation,
    ) -> None:
        """Link an RPC to a message type, or record it as unresolved."""

        # A qualified name such as `example.Cart` is resolved on its last
        # segment, because imports are not followed here.
        local_name = type_name.rsplit(".", 1)[-1]
        target_id = self._messages.get(local_name)

        detail = f"rpc {role} type is '{type_name}'"

        self._add_relationship(
            relationship_type,
            RelationshipOrigin.API_DEFINITION,
            rpc_id,
            target_id or f"unresolved:{type_name}",
            location,
            target_id is not None,
            detail,
        )

        if target_id is None:
            self._result.references.append(
                ResourceReference(
                    id=reference_id(
                        self._file.path,
                        ReferenceKind.PROTO_MESSAGE,
                        type_name,
                        relationship_type.value,
                    ),
                    kind=ReferenceKind.PROTO_MESSAGE,
                    name=type_name,
                    location=location,
                    status=ReferenceStatus.UNRESOLVED,
                    reference_type=relationship_type.value,
                    reason=(
                        "message type is not declared in this file; it may come "
                        "from an import"
                    ),
                    evidence=[
                        ExtractedEvidence(
                            "protobuf_rpc",
                            detail,
                            ExtractionMethod.PROTOBUF,
                            location,
                        )
                    ],
                )
            )

    # ------------------------------------------------------------------ #
    # Scope tracking
    # ------------------------------------------------------------------ #

    def _track_depth(self, line: str) -> None:
        """Track brace depth so RPCs can be attributed to their service."""

        self._depth += line.count("{") - line.count("}")

        if self._current_service is not None and self._depth <= self._service_depth:
            # The service block closed.
            self._current_service = None

    def _package_name(self) -> str | None:
        """Return the declared package name, if any."""

        for resource in self._result.resources:
            if resource.kind is ResourceKind.PROTO_PACKAGE:
                return resource.name

        return None

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
                        "protobuf_declaration",
                        detail,
                        ExtractionMethod.PROTOBUF,
                        location,
                    )
                ],
            )
        )
