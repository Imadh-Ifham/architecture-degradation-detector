"""Language-scoped source patterns.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Extracts scoped client evidence from the languages present in Online
    Boutique: Go, Python, C#, JavaScript/TypeScript and Java.

    This is deliberately not a compiler or a complete call graph. It recognises
    generated gRPC client construction and invocation, common HTTP client calls,
    and cache/database client construction, and it records the identifiers that
    connect a call site to an environment key. The resolver turns those raw
    observations into component relationships.

    Generated code, test files and standalone client/example files are skipped
    before a file reaches this module.
"""

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from app.components.architecture_recovery.source_code_analysis.models import (
    EvidenceStrength,
    EvidenceType,
    FindingType,
    SourceLanguage,
)

#: Source file size cap. Real source files are small; a larger file is usually
#: generated or vendored and is skipped rather than scanned.
MAX_SOURCE_BYTES = 1_048_576


_GENERATED_SUFFIXES = (
    "_pb2.py",
    "_pb2_grpc.py",
    ".pb.go",
    ".pb.gw.go",
    "_grpc.pb.go",
    "_pb.js",
    "_grpc_pb.js",
    "_pb.d.ts",
    "grpc.cs",
    ".g.cs",
    ".designer.cs",
    ".generated.cs",
    ".min.js",
)

_SKIPPED_DIRECTORIES = (
    "/node_modules/",
    "/vendor/",
    "/obj/",
    "/bin/",
    "/dist/",
    "/build/",
    "/generated/",
    "/target/",
)

_STANDALONE_CLIENT_SUFFIXES = (
    "/client.py",
    "/client.js",
    "/client.ts",
    "/client.go",
    "_client.py",
    "_client.js",
    "_client.ts",
)

_TEST_SUFFIXES = (
    "_test.go",
    "_test.py",
    "/test_",
    ".spec.ts",
    ".spec.js",
    ".test.ts",
    ".test.js",
    "tests.cs",
    "test.cs",
)

_EXTENSIONS: dict[str, SourceLanguage] = {
    ".go": SourceLanguage.GO,
    ".py": SourceLanguage.PYTHON,
    ".cs": SourceLanguage.CSHARP,
    ".js": SourceLanguage.JAVASCRIPT,
    ".jsx": SourceLanguage.JAVASCRIPT,
    ".ts": SourceLanguage.TYPESCRIPT,
    ".tsx": SourceLanguage.TYPESCRIPT,
    ".java": SourceLanguage.JAVA,
}


@dataclass(frozen=True)
class RawEvidence:
    """One raw source observation before target resolution."""

    finding_type: FindingType
    evidence_type: EvidenceType
    strength: EvidenceStrength
    target_reference: str
    path: str
    line: int
    language: SourceLanguage
    symbol: str | None = None
    method: str | None = None
    detail: str = ""
    expression: str | None = None


@dataclass
class ScanResult:
    """Everything extracted from one source file."""

    evidence: list[RawEvidence] = field(default_factory=list)
    env_keys: dict[str, str] = field(default_factory=dict)
    assignments: dict[str, str] = field(default_factory=dict)


def language_for(path: str, declared: str | None = None) -> SourceLanguage:
    """Return the language analyzer for a path, or UNKNOWN."""

    suffix = PurePosixPath(path).suffix.lower()

    if suffix in _EXTENSIONS:
        return _EXTENSIONS[suffix]

    if declared:
        normalized = declared.strip().lower()

        for language in SourceLanguage:
            if language.value == normalized:
                return language

        aliases = {
            "js": SourceLanguage.JAVASCRIPT,
            "ts": SourceLanguage.TYPESCRIPT,
            "c#": SourceLanguage.CSHARP,
            "cs": SourceLanguage.CSHARP,
        }

        return aliases.get(normalized, SourceLanguage.UNKNOWN)

    return SourceLanguage.UNKNOWN


def skip_reason(path: str, category: str | None = None) -> str | None:
    """Return why a source path must not be analysed, or None when it may be."""

    normalized = f"/{path.lower().strip('/')}"

    if category == "test":
        return "test_file"

    if any(normalized.endswith(suffix) for suffix in _GENERATED_SUFFIXES):
        return "generated_file"

    if any(directory in normalized for directory in _SKIPPED_DIRECTORIES):
        return "vendored_or_build_directory"

    if any(normalized.endswith(suffix) for suffix in _STANDALONE_CLIENT_SUFFIXES):
        return "standalone_client_file"

    name = PurePosixPath(path).name.lower()

    if name.startswith("test_") or any(
        normalized.endswith(suffix) for suffix in _TEST_SUFFIXES
    ):
        return "test_file"

    return None


def scan_source(path: str, language: SourceLanguage, text: str) -> ScanResult:
    """Extract raw client evidence and identifier mappings from one file."""

    result = ScanResult()

    if language is SourceLanguage.GO:
        _scan_go(path, text, result)
    elif language is SourceLanguage.PYTHON:
        _scan_python(path, text, result)
    elif language is SourceLanguage.CSHARP:
        _scan_csharp(path, text, result)
    elif language in (SourceLanguage.JAVASCRIPT, SourceLanguage.TYPESCRIPT):
        _scan_node(path, language, text, result)
    elif language is SourceLanguage.JAVA:
        _scan_java(path, text, result)

    # Preserve deterministic order and drop exact duplicates.
    unique: dict[tuple, RawEvidence] = {}

    for item in result.evidence:
        key = (
            item.finding_type,
            item.evidence_type,
            item.path,
            item.line,
            item.symbol,
            item.method,
            item.target_reference,
        )
        unique.setdefault(key, item)

    result.evidence = sorted(
        unique.values(),
        key=lambda item: (
            item.path,
            item.line,
            item.finding_type.value,
            item.evidence_type.value,
            item.target_reference,
        ),
    )

    return result


# --------------------------------------------------------------------------- #
# Go
# --------------------------------------------------------------------------- #


_GO_CLIENT = re.compile(r"\b(?:\w+\.)?New(\w+)Client\s*\(")
_GO_ASSIGNMENT = re.compile(r"(?m)^\s*(?:var\s+)?(\w+)(?:\s*,\s*\w+)*\s*:?=\s*(.+)$")
_GO_MAP_ENV = re.compile(
    r"mustMapEnv\s*\(\s*&?\s*[\w.]+\.(\w+)\s*,\s*\"([^\"]+)\"\s*\)"
)
_GO_GETENV_ASSIGNMENT = re.compile(r"(\w+)\s*:?=\s*os\.Getenv\(\"([^\"]+)\"\)")
_GO_HTTP_NEW_REQUEST = re.compile(r"http\.NewRequest\s*\(\s*([^,]+),\s*([^,]+),")
_GO_HTTP_DIRECT = re.compile(r"http\.(Get|Post|Head)\s*\(\s*([^)]+)\)")
_GO_REDIS = re.compile(r"\bredis\.(?:NewClient|NewClusterClient|NewFailoverClient)\s*\(")
_GO_DATABASE = re.compile(r"\b(?:sql\.Open|pgx\.Connect|pgxpool\.New)\s*\(")


def _scan_go(path: str, text: str, result: ScanResult) -> None:
    """Extract Go gRPC, HTTP and infrastructure client evidence."""

    for match in _GO_MAP_ENV.finditer(text):
        result.env_keys[match.group(1)] = match.group(2)

    for match in _GO_GETENV_ASSIGNMENT.finditer(text):
        result.env_keys[match.group(1)] = match.group(2)

    for match in _GO_ASSIGNMENT.finditer(text):
        variable = match.group(1)
        expression = match.group(2).strip()

        if variable and expression and variable not in result.assignments:
            result.assignments[variable] = expression

    for match in _GO_CLIENT.finditer(text):
        service = match.group(1)
        line = _line_of(text, match.start())
        symbol = f"New{service}Client"
        variable = _go_assigned_variable(text, match.start())
        inline_method, inline_line = _go_inline_invocation(text, match.end())

        result.evidence.append(
            RawEvidence(
                finding_type=FindingType.GRPC_SERVICE_CALL,
                evidence_type=EvidenceType.GRPC_CLIENT_CONSTRUCTION,
                strength=EvidenceStrength.CLIENT_CONSTRUCTION,
                target_reference=service,
                path=path,
                line=line,
                language=SourceLanguage.GO,
                symbol=symbol,
                detail=f"constructs a generated gRPC client for '{service}'",
            )
        )

        if inline_method:
            result.evidence.append(
                RawEvidence(
                    finding_type=FindingType.GRPC_SERVICE_CALL,
                    evidence_type=EvidenceType.GRPC_CLIENT_INVOCATION,
                    strength=EvidenceStrength.OBSERVED_INVOCATION,
                    target_reference=service,
                    path=path,
                    line=inline_line,
                    language=SourceLanguage.GO,
                    symbol=symbol,
                    method=inline_method,
                    detail=(
                        f"invokes '{inline_method}' on a generated gRPC client "
                        f"for '{service}'"
                    ),
                )
            )
        elif variable:
            invocation = _invocation_after(text, variable, match.end())

            if invocation:
                method, invocation_line = invocation
                result.evidence.append(
                    RawEvidence(
                        finding_type=FindingType.GRPC_SERVICE_CALL,
                        evidence_type=EvidenceType.GRPC_CLIENT_INVOCATION,
                        strength=EvidenceStrength.OBSERVED_INVOCATION,
                        target_reference=service,
                        path=path,
                        line=invocation_line,
                        language=SourceLanguage.GO,
                        symbol=variable,
                        method=method,
                        detail=(
                            f"invokes '{method}' on a generated gRPC client "
                            f"for '{service}'"
                        ),
                    )
                )

    for match in _GO_HTTP_NEW_REQUEST.finditer(text):
        method = _http_method(match.group(1))
        expression = match.group(2).strip()
        reference = sanitize_reference(expression)
        result.evidence.append(
            RawEvidence(
                finding_type=FindingType.HTTP_SERVICE_CALL,
                evidence_type=EvidenceType.HTTP_CLIENT_INVOCATION,
                strength=EvidenceStrength.OBSERVED_INVOCATION,
                target_reference=reference,
                path=path,
                line=_line_of(text, match.start()),
                language=SourceLanguage.GO,
                method=method,
                detail=f"performs an HTTP {method} request to '{reference}'",
                expression=expression,
            )
        )

    for match in _GO_HTTP_DIRECT.finditer(text):
        method = match.group(1).upper()
        expression = match.group(2).strip()
        reference = sanitize_reference(expression)
        result.evidence.append(
            RawEvidence(
                finding_type=FindingType.HTTP_SERVICE_CALL,
                evidence_type=EvidenceType.HTTP_CLIENT_INVOCATION,
                strength=EvidenceStrength.OBSERVED_INVOCATION,
                target_reference=reference,
                path=path,
                line=_line_of(text, match.start()),
                language=SourceLanguage.GO,
                method=method,
                detail=f"performs an HTTP {method} request to '{reference}'",
                expression=expression,
            )
        )

    if _GO_REDIS.search(text):
        match = _GO_REDIS.search(text)
        result.evidence.append(
            RawEvidence(
                finding_type=FindingType.CACHE_CLIENT_USAGE,
                evidence_type=EvidenceType.CACHE_CLIENT_CONSTRUCTION,
                strength=EvidenceStrength.CLIENT_CONSTRUCTION,
                target_reference="redis",
                path=path,
                line=_line_of(text, match.start()),
                language=SourceLanguage.GO,
                symbol="redis.NewClient",
                detail="constructs a Redis cache client",
            )
        )

    if _GO_DATABASE.search(text):
        match = _GO_DATABASE.search(text)
        result.evidence.append(
            RawEvidence(
                finding_type=FindingType.DATABASE_CLIENT_USAGE,
                evidence_type=EvidenceType.DATABASE_CLIENT_CONSTRUCTION,
                strength=EvidenceStrength.CLIENT_CONSTRUCTION,
                target_reference="database",
                path=path,
                line=_line_of(text, match.start()),
                language=SourceLanguage.GO,
                symbol=match.group(0).split("(")[0],
                detail="constructs a database client",
            )
        )


def _go_assigned_variable(text: str, constructor_start: int) -> str | None:
    """Return the variable receiving a client construction, when there is one."""

    line_start = text.rfind("\n", 0, constructor_start) + 1
    prefix = text[line_start:constructor_start]
    match = re.search(r"(\w+)(?:\s*,\s*\w+)*\s*:?=\s*[\w.]*$", prefix)

    return match.group(1) if match else None


def _go_inline_invocation(text: str, open_index: int) -> tuple[str | None, int]:
    """Return the method invoked directly after a client construction."""

    close_index = _find_matching_paren(text, open_index - 1)

    if close_index is None:
        return None, 0

    match = re.match(r"\s*\.\s*(\w+)\s*\(", text[close_index + 1 :])

    if not match:
        return None, 0

    return match.group(1), _line_of(text, close_index + 1 + match.start())


# --------------------------------------------------------------------------- #
# Python
# --------------------------------------------------------------------------- #


_PY_STUB = re.compile(r"(?m)^\s*(\w+)\s*=\s*([\w.]+)\.(\w+)Stub\s*\(")
_PY_ASSIGNMENT = re.compile(r"(?m)^\s*(\w+)\s*=\s*([^\n#]+)$")
_PY_ENV_GET = re.compile(
    r"(\w+)\s*=\s*os\.(?:environ\.get|getenv)\(\s*['\"]([^'\"]+)['\"]"
)
_PY_ENV_INDEX = re.compile(
    r"(\w+)\s*=\s*os\.environ\[\s*['\"]([^'\"]+)['\"]\s*\]"
)
_PY_HTTP = re.compile(
    r"\b(?:requests|httpx)\.(get|post|put|delete|patch|head)\s*\(\s*([^,)]+)"
)
_PY_LOCUST = re.compile(
    r"\b[\w.]+\.client\.(get|post|put|delete|patch|head)\s*\(\s*([^,)]+)"
)
_PY_REDIS = re.compile(r"\b(?:redis\.(?:Redis|StrictRedis|from_url))\s*\(")
_PY_DATABASE = re.compile(
    r"\b(?:psycopg(?:2)?\.connect|asyncpg\.connect|sqlalchemy\.create_engine)\s*\("
)


def _scan_python(path: str, text: str, result: ScanResult) -> None:
    """Extract Python gRPC, HTTP and infrastructure client evidence."""

    for match in _PY_ENV_GET.finditer(text):
        result.env_keys[match.group(1)] = match.group(2)

    for match in _PY_ENV_INDEX.finditer(text):
        result.env_keys[match.group(1)] = match.group(2)

    for match in _PY_ASSIGNMENT.finditer(text):
        variable = match.group(1)
        expression = match.group(2).strip()

        if variable and expression and variable not in result.assignments:
            result.assignments[variable] = expression

    for match in _PY_STUB.finditer(text):
        variable = match.group(1)
        service = match.group(3)
        symbol = f"{match.group(2)}.{service}Stub"
        line = _line_of(text, match.start())

        result.evidence.append(
            RawEvidence(
                finding_type=FindingType.GRPC_SERVICE_CALL,
                evidence_type=EvidenceType.GRPC_CLIENT_CONSTRUCTION,
                strength=EvidenceStrength.CLIENT_CONSTRUCTION,
                target_reference=service,
                path=path,
                line=line,
                language=SourceLanguage.PYTHON,
                symbol=symbol,
                detail=f"constructs a generated gRPC stub for '{service}'",
            )
        )

        # Python stubs are often module-level and invoked from a class defined
        # earlier in the file, so search the whole file when no forward call is
        # found.
        invocation = _invocation_after(text, variable, match.end()) or _invocation_before(
            text, variable, match.start()
        )

        if invocation:
            method, invocation_line = invocation
            result.evidence.append(
                RawEvidence(
                    finding_type=FindingType.GRPC_SERVICE_CALL,
                    evidence_type=EvidenceType.GRPC_CLIENT_INVOCATION,
                    strength=EvidenceStrength.OBSERVED_INVOCATION,
                    target_reference=service,
                    path=path,
                    line=invocation_line,
                    language=SourceLanguage.PYTHON,
                    symbol=variable,
                    method=method,
                    detail=(
                        f"invokes '{method}' on a generated gRPC stub for "
                        f"'{service}'"
                    ),
                )
            )

    for pattern in (_PY_HTTP, _PY_LOCUST):
        for match in pattern.finditer(text):
            method = match.group(1).upper()
            expression = match.group(2).strip()
            reference = sanitize_reference(expression)
            result.evidence.append(
                RawEvidence(
                    finding_type=FindingType.HTTP_SERVICE_CALL,
                    evidence_type=EvidenceType.HTTP_CLIENT_INVOCATION,
                    strength=EvidenceStrength.OBSERVED_INVOCATION,
                    target_reference=reference,
                    path=path,
                    line=_line_of(text, match.start()),
                    language=SourceLanguage.PYTHON,
                    method=method,
                    detail=f"performs an HTTP {method} request to '{reference}'",
                    expression=expression,
                )
            )

    if _PY_REDIS.search(text):
        match = _PY_REDIS.search(text)
        result.evidence.append(
            RawEvidence(
                finding_type=FindingType.CACHE_CLIENT_USAGE,
                evidence_type=EvidenceType.CACHE_CLIENT_CONSTRUCTION,
                strength=EvidenceStrength.CLIENT_CONSTRUCTION,
                target_reference="redis",
                path=path,
                line=_line_of(text, match.start()),
                language=SourceLanguage.PYTHON,
                symbol="redis.Redis",
                detail="constructs a Redis cache client",
            )
        )

    if _PY_DATABASE.search(text):
        match = _PY_DATABASE.search(text)
        result.evidence.append(
            RawEvidence(
                finding_type=FindingType.DATABASE_CLIENT_USAGE,
                evidence_type=EvidenceType.DATABASE_CLIENT_CONSTRUCTION,
                strength=EvidenceStrength.CLIENT_CONSTRUCTION,
                target_reference="database",
                path=path,
                line=_line_of(text, match.start()),
                language=SourceLanguage.PYTHON,
                symbol=match.group(0).split("(")[0],
                detail="constructs a database client",
            )
        )


# --------------------------------------------------------------------------- #
# C#
# --------------------------------------------------------------------------- #


_CS_GRPC = re.compile(r"new\s+(\w+)\.(\w+)Client\s*\(")
_CS_ASSIGNMENT = re.compile(r"(?m)^\s*(?:var\s+)?(\w+)\s*=\s*(.+)$")
_CS_CONFIG = re.compile(r"Configuration\[\s*\"([^\"]+)\"\s*\]")
_CS_ENV = re.compile(r"Environment\.GetEnvironmentVariable\(\s*\"([^\"]+)\"\s*\)")
_CS_HTTP = re.compile(r"\.(GetAsync|PostAsync|PutAsync|DeleteAsync)\s*\(\s*([^,)]+)")
_CS_REDIS_CONFIG = re.compile(
    r"AddStackExchangeRedisCache|ConnectionMultiplexer\.Connect"
)
_CS_CACHE_OPERATION = re.compile(r"\b(\w+)\.(GetAsync|SetAsync|RemoveAsync)\s*\(")
_CS_DATABASE = re.compile(
    r"\b(?:new\s+(?:NpgsqlConnection|SqlConnection)|UseNpgsql|UseSqlServer)"
)


def _scan_csharp(path: str, text: str, result: ScanResult) -> None:
    """Extract C# gRPC, HTTP and cache/database evidence."""

    for match in _CS_CONFIG.finditer(text):
        result.env_keys[match.group(1)] = match.group(1)

    for match in _CS_ENV.finditer(text):
        result.env_keys[match.group(1)] = match.group(1)

    for match in _CS_ASSIGNMENT.finditer(text):
        variable = match.group(1)
        expression = match.group(2).strip()

        if variable and expression and variable not in result.assignments:
            result.assignments[variable] = expression

    for match in _CS_GRPC.finditer(text):
        service = match.group(2)
        symbol = f"{match.group(1)}.{service}Client"
        line = _line_of(text, match.start())
        variable = _csharp_assigned_variable(text, match.start())

        result.evidence.append(
            RawEvidence(
                finding_type=FindingType.GRPC_SERVICE_CALL,
                evidence_type=EvidenceType.GRPC_CLIENT_CONSTRUCTION,
                strength=EvidenceStrength.CLIENT_CONSTRUCTION,
                target_reference=service,
                path=path,
                line=line,
                language=SourceLanguage.CSHARP,
                symbol=symbol,
                detail=f"constructs a generated gRPC client for '{service}'",
            )
        )

        if variable:
            invocation = _invocation_after(text, variable, match.end())

            if invocation:
                method, invocation_line = invocation
                result.evidence.append(
                    RawEvidence(
                        finding_type=FindingType.GRPC_SERVICE_CALL,
                        evidence_type=EvidenceType.GRPC_CLIENT_INVOCATION,
                        strength=EvidenceStrength.OBSERVED_INVOCATION,
                        target_reference=service,
                        path=path,
                        line=invocation_line,
                        language=SourceLanguage.CSHARP,
                        symbol=variable,
                        method=method,
                        detail=(
                            f"invokes '{method}' on a generated gRPC client "
                            f"for '{service}'"
                        ),
                    )
                )

    # `.GetAsync` is also an IDistributedCache operation, so only treat it as
    # HTTP in a file that actually uses HttpClient and a URL-like argument.
    if "HttpClient" in text:
        for match in _CS_HTTP.finditer(text):
            method = match.group(1).replace("Async", "").upper()
            expression = match.group(2).strip()

            if not (
                expression.startswith(('"', "'", "/"))
                or "url" in expression.lower()
                or "endpoint" in expression.lower()
            ):
                continue

            reference = sanitize_reference(expression)
            result.evidence.append(
                RawEvidence(
                    finding_type=FindingType.HTTP_SERVICE_CALL,
                    evidence_type=EvidenceType.HTTP_CLIENT_INVOCATION,
                    strength=EvidenceStrength.OBSERVED_INVOCATION,
                    target_reference=reference,
                    path=path,
                    line=_line_of(text, match.start()),
                    language=SourceLanguage.CSHARP,
                    method=method,
                    detail=f"performs an HTTP {method} request to '{reference}'",
                    expression=expression,
                )
            )

    if _CS_REDIS_CONFIG.search(text):
        match = _CS_REDIS_CONFIG.search(text)
        result.evidence.append(
            RawEvidence(
                finding_type=FindingType.CACHE_CLIENT_USAGE,
                evidence_type=EvidenceType.CACHE_CLIENT_CONSTRUCTION,
                strength=EvidenceStrength.CLIENT_CONSTRUCTION,
                target_reference="redis",
                path=path,
                line=_line_of(text, match.start()),
                language=SourceLanguage.CSHARP,
                symbol="AddStackExchangeRedisCache",
                detail="configures a Redis distributed cache client",
            )
        )

    # IDistributedCache operations are cache evidence only in a file that
    # actually declares or uses the Redis-backed cache abstraction.
    if "IDistributedCache" in text or "RedisCartStore" in text:
        for match in _CS_CACHE_OPERATION.finditer(text):
            method = match.group(2)
            result.evidence.append(
                RawEvidence(
                    finding_type=FindingType.CACHE_CLIENT_USAGE,
                    evidence_type=EvidenceType.CACHE_CLIENT_INVOCATION,
                    strength=EvidenceStrength.OBSERVED_INVOCATION,
                    target_reference="redis",
                    path=path,
                    line=_line_of(text, match.start()),
                    language=SourceLanguage.CSHARP,
                    symbol=match.group(1),
                    method=method,
                    detail=f"invokes '{method}' on the distributed cache client",
                )
            )

    if _CS_DATABASE.search(text):
        match = _CS_DATABASE.search(text)
        result.evidence.append(
            RawEvidence(
                finding_type=FindingType.DATABASE_CLIENT_USAGE,
                evidence_type=EvidenceType.DATABASE_CLIENT_CONSTRUCTION,
                strength=EvidenceStrength.CLIENT_CONSTRUCTION,
                target_reference="database",
                path=path,
                line=_line_of(text, match.start()),
                language=SourceLanguage.CSHARP,
                symbol=match.group(0),
                detail="configures a database client",
            )
        )


def _csharp_assigned_variable(text: str, constructor_start: int) -> str | None:
    """Return the variable receiving a C# client construction."""

    line_start = text.rfind("\n", 0, constructor_start) + 1
    prefix = text[line_start:constructor_start]
    match = re.search(r"(?:var\s+)?(\w+)\s*=\s*$", prefix)

    return match.group(1) if match else None


# --------------------------------------------------------------------------- #
# JavaScript / TypeScript
# --------------------------------------------------------------------------- #


_NODE_GRPC = re.compile(r"new\s+(?:[\w.]+\.)?(\w+)Client\s*\(")
_NODE_ASSIGNMENT = re.compile(r"(?m)^\s*(?:const|let|var)\s+(\w+)\s*=\s*(.+)$")
_NODE_ENV_DOT = re.compile(r"process\.env\.([A-Za-z_]\w*)")
_NODE_ENV_INDEX = re.compile(r"process\.env\[\s*['\"]([^'\"]+)['\"]\s*\]")
_NODE_FETCH = re.compile(r"\bfetch\s*\(\s*([^,)]+)")
_NODE_AXIOS = re.compile(r"\baxios\.(get|post|put|delete|patch)\s*\(\s*([^,)]+)")
_NODE_HTTP = re.compile(r"\b(?:http|https)\.(get|request)\s*\(\s*([^,)]+)")
_NODE_REDIS = re.compile(r"\b(?:redis\.createClient|new\s+Redis\s*\(|ioredis)")
_NODE_DATABASE = re.compile(
    r"\b(?:new\s+Pool\s*\(|pg\.Pool|mysql\.createConnection|mongoose\.connect)"
)


def _scan_node(
    path: str, language: SourceLanguage, text: str, result: ScanResult
) -> None:
    """Extract Node.js client evidence."""

    for match in _NODE_ENV_DOT.finditer(text):
        result.env_keys[match.group(1)] = match.group(1)

    for match in _NODE_ENV_INDEX.finditer(text):
        result.env_keys[match.group(1)] = match.group(1)

    for match in _NODE_ASSIGNMENT.finditer(text):
        variable = match.group(1)
        expression = match.group(2).strip()

        if variable and expression and variable not in result.assignments:
            result.assignments[variable] = expression

    for match in _NODE_GRPC.finditer(text):
        service = match.group(1)
        symbol = f"{service}Client"
        line = _line_of(text, match.start())
        variable = _node_assigned_variable(text, match.start())

        result.evidence.append(
            RawEvidence(
                finding_type=FindingType.GRPC_SERVICE_CALL,
                evidence_type=EvidenceType.GRPC_CLIENT_CONSTRUCTION,
                strength=EvidenceStrength.CLIENT_CONSTRUCTION,
                target_reference=service,
                path=path,
                line=line,
                language=language,
                symbol=symbol,
                detail=f"constructs a gRPC client for '{service}'",
            )
        )

        if variable:
            invocation = _invocation_after(text, variable, match.end())

            if invocation:
                method, invocation_line = invocation
                result.evidence.append(
                    RawEvidence(
                        finding_type=FindingType.GRPC_SERVICE_CALL,
                        evidence_type=EvidenceType.GRPC_CLIENT_INVOCATION,
                        strength=EvidenceStrength.OBSERVED_INVOCATION,
                        target_reference=service,
                        path=path,
                        line=invocation_line,
                        language=language,
                        symbol=variable,
                        method=method,
                        detail=(
                            f"invokes '{method}' on a gRPC client for '{service}'"
                        ),
                    )
                )

    for match in _NODE_FETCH.finditer(text):
        expression = match.group(1).strip()
        reference = sanitize_reference(expression)
        result.evidence.append(
            RawEvidence(
                finding_type=FindingType.HTTP_SERVICE_CALL,
                evidence_type=EvidenceType.HTTP_CLIENT_INVOCATION,
                strength=EvidenceStrength.OBSERVED_INVOCATION,
                target_reference=reference,
                path=path,
                line=_line_of(text, match.start()),
                language=language,
                method="GET",
                detail=f"performs an HTTP GET request to '{reference}'",
                expression=expression,
            )
        )

    for pattern in (_NODE_AXIOS, _NODE_HTTP):
        for match in pattern.finditer(text):
            method = match.group(1).upper()

            if method == "REQUEST":
                method = "GET"

            expression = match.group(2).strip()
            reference = sanitize_reference(expression)
            result.evidence.append(
                RawEvidence(
                    finding_type=FindingType.HTTP_SERVICE_CALL,
                    evidence_type=EvidenceType.HTTP_CLIENT_INVOCATION,
                    strength=EvidenceStrength.OBSERVED_INVOCATION,
                    target_reference=reference,
                    path=path,
                    line=_line_of(text, match.start()),
                    language=language,
                    method=method,
                    detail=f"performs an HTTP {method} request to '{reference}'",
                    expression=expression,
                )
            )

    if _NODE_REDIS.search(text):
        match = _NODE_REDIS.search(text)
        result.evidence.append(
            RawEvidence(
                finding_type=FindingType.CACHE_CLIENT_USAGE,
                evidence_type=EvidenceType.CACHE_CLIENT_CONSTRUCTION,
                strength=EvidenceStrength.CLIENT_CONSTRUCTION,
                target_reference="redis",
                path=path,
                line=_line_of(text, match.start()),
                language=language,
                symbol="redis.createClient",
                detail="constructs a Redis cache client",
            )
        )

    if _NODE_DATABASE.search(text):
        match = _NODE_DATABASE.search(text)
        result.evidence.append(
            RawEvidence(
                finding_type=FindingType.DATABASE_CLIENT_USAGE,
                evidence_type=EvidenceType.DATABASE_CLIENT_CONSTRUCTION,
                strength=EvidenceStrength.CLIENT_CONSTRUCTION,
                target_reference="database",
                path=path,
                line=_line_of(text, match.start()),
                language=language,
                symbol=match.group(0),
                detail="constructs a database client",
            )
        )


def _node_assigned_variable(text: str, constructor_start: int) -> str | None:
    """Return the variable receiving a Node client construction."""

    line_start = text.rfind("\n", 0, constructor_start) + 1
    prefix = text[line_start:constructor_start]
    match = re.search(r"(?:const|let|var)\s+(\w+)\s*=\s*$", prefix)

    return match.group(1) if match else None


# --------------------------------------------------------------------------- #
# Java
# --------------------------------------------------------------------------- #


_JAVA_GRPC = re.compile(r"(\w+)Grpc\.(newBlockingStub|newStub|newFutureStub)\s*\(")
_JAVA_ASSIGNMENT = re.compile(r"(?m)^\s*(?:var\s+)?(\w+)\s*=\s*(.+)$")
_JAVA_ENV = re.compile(r"System\.getenv\(\s*\"([^\"]+)\"\s*\)")


def _scan_java(path: str, text: str, result: ScanResult) -> None:
    """Extract Java gRPC client evidence."""

    for match in _JAVA_ENV.finditer(text):
        result.env_keys[match.group(1)] = match.group(1)

    for match in _JAVA_ASSIGNMENT.finditer(text):
        variable = match.group(1)
        expression = match.group(2).strip()

        if variable and expression and variable not in result.assignments:
            result.assignments[variable] = expression

    for match in _JAVA_GRPC.finditer(text):
        service = match.group(1)
        symbol = f"{service}Grpc.{match.group(2)}"
        line = _line_of(text, match.start())
        variable = _java_assigned_variable(text, match.start())

        result.evidence.append(
            RawEvidence(
                finding_type=FindingType.GRPC_SERVICE_CALL,
                evidence_type=EvidenceType.GRPC_CLIENT_CONSTRUCTION,
                strength=EvidenceStrength.CLIENT_CONSTRUCTION,
                target_reference=service,
                path=path,
                line=line,
                language=SourceLanguage.JAVA,
                symbol=symbol,
                detail=f"constructs a gRPC stub for '{service}'",
            )
        )

        if variable:
            invocation = _invocation_after(text, variable, match.end())

            if invocation:
                method, invocation_line = invocation
                result.evidence.append(
                    RawEvidence(
                        finding_type=FindingType.GRPC_SERVICE_CALL,
                        evidence_type=EvidenceType.GRPC_CLIENT_INVOCATION,
                        strength=EvidenceStrength.OBSERVED_INVOCATION,
                        target_reference=service,
                        path=path,
                        line=invocation_line,
                        language=SourceLanguage.JAVA,
                        symbol=variable,
                        method=method,
                        detail=f"invokes '{method}' on a gRPC stub for '{service}'",
                    )
                )


def _java_assigned_variable(text: str, constructor_start: int) -> str | None:
    """Return the variable receiving a Java stub construction."""

    line_start = text.rfind("\n", 0, constructor_start) + 1
    prefix = text[line_start:constructor_start]
    match = re.search(r"(?:var\s+)?(\w+)\s*=\s*$", prefix)

    return match.group(1) if match else None


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _line_of(text: str, index: int) -> int:
    """Return the 1-based line number of a character index."""

    return text.count("\n", 0, index) + 1


def _find_matching_paren(text: str, open_index: int) -> int | None:
    """Return the index of the closing parenthesis matching `open_index`."""

    if open_index < 0 or open_index >= len(text) or text[open_index] != "(":
        return None

    depth = 0

    for index in range(open_index, len(text)):
        character = text[index]

        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1

            if depth == 0:
                return index

    return None


def _invocation_after(
    text: str, variable: str, start_index: int, window: int = 6000
) -> tuple[str, int] | None:
    """Return the first `variable.method(` after a construction."""

    pattern = re.compile(rf"\b{re.escape(variable)}\.(\w+)\s*\(")
    match = pattern.search(text, start_index, start_index + window)

    if not match:
        return None

    return match.group(1), _line_of(text, match.start())


def _invocation_before(
    text: str, variable: str, end_index: int
) -> tuple[str, int] | None:
    """Return the nearest `variable.method(` before a construction."""

    pattern = re.compile(rf"\b{re.escape(variable)}\.(\w+)\s*\(")
    match = None

    for candidate in pattern.finditer(text, 0, end_index):
        match = candidate

    if not match:
        return None

    return match.group(1), _line_of(text, match.start())


def _http_method(expression: str) -> str:
    """Turn a Go HTTP method expression into a method name."""

    value = expression.strip()
    value = value.removeprefix("http.Method").strip("\"'")

    return value.upper() or "GET"


def sanitize_reference(expression: str) -> str:
    """Reduce an HTTP expression to a safe, bounded reference."""

    value = expression.strip()
    value = value.strip("`")

    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        value = value[1:-1]

    if "://" in value and "@" in value.split("://", 1)[1].split("/", 1)[0]:
        scheme, rest = value.split("://", 1)
        value = f"{scheme}://{rest.split('@', 1)[1]}"

    value = " ".join(value.split())

    if len(value) > 200:
        value = value[:197] + "..."

    return value or "<unnamed request>"


__all__ = [
    "MAX_SOURCE_BYTES",
    "RawEvidence",
    "ScanResult",
    "language_for",
    "sanitize_reference",
    "scan_source",
    "skip_reason",
]
