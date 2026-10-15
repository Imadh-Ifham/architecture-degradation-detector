"""Dockerfile analyzer.

Author: Imadh Ifham
Date: 2026-10-14
Description:
    Parses Dockerfiles into build stages, base images, exposed ports, runtime
    configuration and build inputs.

    The file is parsed as text; no instruction is ever executed, no build is
    triggered and no shell in the repository is invoked. Values that could carry
    credentials are redacted, and `COPY --from` is resolved against the stages
    declared in the same file.
"""

import re
from pathlib import Path
from typing import Iterator

from app.components.architecture_recovery.manifest_analysis.base import (
    AnalyzerResult,
    ManifestAnalyzer,
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
    ReferenceKind,
    ReferenceStatus,
    RelationshipOrigin,
    RelationshipType,
    ResourceKind,
    ResourceReference,
    SourceLocation,
    endpoint_id,
    reference_id,
    relationship_id,
    resource_id,
)
from app.components.architecture_recovery.manifest_analysis.redaction import (
    extract_endpoint_candidate,
    sanitize_scalar,
)
from app.components.architecture_recovery.repository_inventory.models import (
    FileRecord,
)

# Instructions whose first argument is a port list.
_PORT_INSTRUCTION = "EXPOSE"

# Instructions recorded as runtime configuration rather than as resources.
_RUNTIME_INSTRUCTIONS = frozenset(
    {"ENTRYPOINT", "CMD", "HEALTHCHECK", "STOPSIGNAL", "SHELL", "USER", "WORKDIR"}
)

# Instructions whose values must never be recorded verbatim.
_SENSITIVE_INSTRUCTIONS = frozenset({"ENV", "ARG", "LABEL"})

# `FROM [--platform=x] image [AS stage]`
_FROM_PATTERN = re.compile(
    r"^(?:--\S+\s+)*(?P<image>\S+)(?:\s+[Aa][Ss]\s+(?P<stage>\S+))?\s*$"
)

# Maximum length recorded for a free-text instruction argument.
_MAX_ARGUMENT_LENGTH = 500


class DockerfileAnalyzer(ManifestAnalyzer):
    """Analyzes a Dockerfile."""

    name = "dockerfile"

    def __init__(self, max_bytes: int = 1_048_576) -> None:
        """Store the maximum number of bytes read from a single file."""

        self._max_bytes = max_bytes

    def can_analyze(self, file: FileRecord) -> bool:
        """Accept any file the inventory classified as a Dockerfile."""

        return file.format == "dockerfile"

    def analyze(self, file: FileRecord, absolute_path: Path) -> AnalyzerResult:
        """Extract stages, base images, ports and build inputs."""

        result = AnalyzerResult(method=ExtractionMethod.DOCKERFILE)

        text, diagnostic = read_manifest_text(
            absolute_path, self._max_bytes, file.path
        )

        if text is None:
            result.status = ParseStatus.SKIPPED
            result.diagnostics.append(diagnostic)
            return result

        analysis = _DockerfileAnalysis(file, result)
        analysis.run(text)

        if not result.resources:
            result.status = ParseStatus.PARTIAL

        return result


def _instructions(text: str) -> Iterator[tuple[int, str, str]]:
    """Yield `(line_number, instruction, argument)` for each Dockerfile line.

    Handles backslash continuations (reporting the first line of the
    instruction) and skips comments and blank lines.
    """

    pending: list[str] = []
    start_line = 0

    for index, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip()

        if not pending:
            stripped = line.strip()

            # A comment line, or a blank line between instructions.
            if not stripped or stripped.startswith("#"):
                continue

            start_line = index

        # A trailing backslash continues the instruction onto the next line.
        if line.endswith("\\"):
            pending.append(line[:-1])
            continue

        pending.append(line)
        joined = " ".join(pending).strip()
        pending = []

        if not joined or joined.startswith("#"):
            continue

        instruction, _, argument = joined.partition(" ")

        yield start_line, instruction.upper(), argument.strip()

    if pending:
        # Unterminated continuation: yield what was collected rather than
        # silently dropping the tail of the file.
        joined = " ".join(pending).strip()

        if joined:
            instruction, _, argument = joined.partition(" ")
            yield start_line, instruction.upper(), argument.strip()


class _DockerfileAnalysis:
    """Walks one Dockerfile and records its declarations."""

    def __init__(self, file: FileRecord, result: AnalyzerResult) -> None:
        """Bind the analysis to a file and its result."""

        self._file = file
        self._result = result

        self._stages: dict[str, str] = {}
        self._images: dict[str, str] = {}
        self._stage_index = 0
        self._current_stage_id: str | None = None
        self._declared_files: set[str] = set()

    def run(self, text: str) -> None:
        """Process every instruction in order."""

        for line_number, instruction, argument in _instructions(text):
            location = SourceLocation(path=self._file.path, line=line_number)

            if instruction == "FROM":
                self._from_(argument, location)
            elif instruction == _PORT_INSTRUCTION:
                self._expose(argument, location)
            elif instruction in ("ENV", "ARG"):
                self._environment(instruction, argument, location)
            elif instruction == "LABEL":
                self._labels(argument, location)
            elif instruction in _RUNTIME_INSTRUCTIONS:
                self._runtime(instruction, argument, location)
            elif instruction in ("COPY", "ADD"):
                self._copy(instruction, argument, location)

    # ------------------------------------------------------------------ #
    # Instructions
    # ------------------------------------------------------------------ #

    def _from_(self, argument: str, location: SourceLocation) -> None:
        """Record a build stage and the image or stage it builds from."""

        match = _FROM_PATTERN.match(argument)

        if not match:
            self._result.add_diagnostic(
                DiagnosticSeverity.WARNING,
                f"could not parse FROM instruction: '{argument}'",
                self._file.path,
                location.line,
                "dockerfile",
            )
            return

        image = match.group("image")
        # An unnamed stage is still a stage; it is identified by its position.
        stage_name = match.group("stage") or f"stage-{self._stage_index}"

        self._stage_index += 1

        stage_id = resource_id(self._file.path, ResourceKind.BUILD_STAGE, stage_name)
        self._stages[stage_name] = stage_id
        self._current_stage_id = stage_id

        attributes: dict = {"base_image": image, "index": self._stage_index - 1}

        if self._file.component_id:
            # Evidence connecting this Dockerfile to the candidate application
            # the inventory associated with it.
            attributes["component_id"] = self._file.component_id

        self._result.resources.append(
            DeclaredResource(
                id=stage_id,
                kind=ResourceKind.BUILD_STAGE,
                name=stage_name,
                location=location,
                analyzer="dockerfile",
                method=ExtractionMethod.DOCKERFILE,
                attributes=attributes,
                evidence=[
                    ExtractedEvidence(
                        "dockerfile_from",
                        f"stage '{stage_name}' builds from '{image}'",
                        ExtractionMethod.DOCKERFILE,
                        location,
                    )
                ],
            )
        )

        # A base that names an earlier stage in this file is an internal
        # dependency; anything else is an external image reference.
        if image in self._stages:
            self._add_relationship(
                RelationshipType.BUILDS_FROM,
                RelationshipOrigin.DECLARED_BUILD_INPUT,
                stage_id,
                self._stages[image],
                location,
                True,
                f"stage '{stage_name}' builds from the earlier stage '{image}'",
            )
            return

        image_id = self._images.get(image)

        if image_id is None:
            image_id = resource_id(self._file.path, ResourceKind.IMAGE, image)
            self._images[image] = image_id
            self._result.resources.append(
                DeclaredResource(
                    id=image_id,
                    kind=ResourceKind.IMAGE,
                    name=image,
                    location=location,
                    analyzer="dockerfile",
                    method=ExtractionMethod.DOCKERFILE,
                    attributes={"reference": image},
                    evidence=[
                        ExtractedEvidence(
                            "dockerfile_base_image",
                            f"base image '{image}' is declared",
                            ExtractionMethod.DOCKERFILE,
                            location,
                        )
                    ],
                )
            )

        self._add_relationship(
            RelationshipType.BUILDS_FROM,
            RelationshipOrigin.DECLARED_BUILD_INPUT,
            stage_id,
            image_id,
            location,
            True,
            f"stage '{stage_name}' builds from base image '{image}'",
        )

    def _expose(self, argument: str, location: SourceLocation) -> None:
        """Record exposed ports as endpoints."""

        for token in argument.split():
            port_text = token.split("/", 1)[0]

            if not port_text.isdigit():
                continue

            protocol = (
                token.split("/", 1)[1].lower() if "/" in token else "tcp"
            )
            port = int(port_text)

            endpoint = Endpoint(
                id=endpoint_id(self._file.path, f"expose:{port}/{protocol}"),
                location=location,
                port=port,
                protocol=protocol,
                source_resource_id=self._current_stage_id,
                scope="image",
                evidence=[
                    ExtractedEvidence(
                        "dockerfile_expose",
                        f"image declares the exposed port {port}/{protocol}",
                        ExtractionMethod.DOCKERFILE,
                        location,
                    )
                ],
            )

            self._result.endpoints.append(endpoint)

            if self._current_stage_id:
                self._add_relationship(
                    RelationshipType.EXPOSES_PORT,
                    RelationshipOrigin.CONFIGURED_ENDPOINT,
                    self._current_stage_id,
                    endpoint.id,
                    location,
                    True,
                    f"stage exposes port {port}/{protocol}",
                )

    def _environment(
        self, instruction: str, argument: str, location: SourceLocation
    ) -> None:
        """Record variable names and any endpoint a value configures."""

        # Both `ENV key=value` and the legacy `ENV key value` forms are used.
        pairs = _key_value_pairs(argument, self._variables())

        if not pairs:
            return

        recorded = self._stage_attribute("environment")
        recorded_args = self._stage_attribute("build_arguments")
        target = recorded_args if instruction == "ARG" else recorded

        for key, value in pairs:
            sanitized = sanitize_scalar(value, key)

            item: dict = {"name": key}

            if sanitized.value is not None:
                item["value"] = sanitized.value

            if sanitized.redacted:
                item["redacted"] = True

            target.append(item)

            if sanitized.value is None:
                continue

            candidate = extract_endpoint_candidate(sanitized.value)

            if candidate is None:
                continue

            endpoint = Endpoint(
                id=endpoint_id(self._file.path, f"{instruction.lower()}:{key}"),
                location=location,
                host=candidate.host,
                port=candidate.port,
                protocol=candidate.scheme,
                source_resource_id=self._current_stage_id,
                scope="build_configuration",
                evidence=[
                    ExtractedEvidence(
                        "dockerfile_environment",
                        f"{instruction} '{key}' configures the endpoint "
                        f"'{candidate.sanitized_value}'",
                        ExtractionMethod.DOCKERFILE,
                        location,
                    )
                ],
            )

            self._result.endpoints.append(endpoint)

            if self._current_stage_id:
                self._add_relationship(
                    RelationshipType.REFERS_TO_SERVICE,
                    RelationshipOrigin.CONFIGURED_ENDPOINT,
                    self._current_stage_id,
                    endpoint.id,
                    location,
                    True,
                    f"{instruction} '{key}' configures the endpoint "
                    f"'{candidate.sanitized_value}'",
                )

    def _variables(self) -> dict[str, str]:
        """Return the variables declared so far, for `$VAR` expansion."""

        variables: dict[str, str] = {}

        for resource in self._result.resources:
            if resource.kind is not ResourceKind.BUILD_STAGE:
                continue

            for entry in resource.attributes.get("environment", []):
                if "value" in entry:
                    variables[entry["name"]] = entry["value"]

        return variables

    def _labels(self, argument: str, location: SourceLocation) -> None:
        """Record label keys, redacting values that look sensitive."""

        pairs = _key_value_pairs(argument, self._variables())

        if not pairs:
            return

        labels: dict[str, str] = {}
        redacted: list[str] = []

        for key, value in pairs:
            sanitized = sanitize_scalar(value, key)

            if sanitized.redacted:
                redacted.append(key)
                continue

            labels[key] = sanitized.value or ""

        if labels:
            self._stage_attribute("labels").append(labels)

        if redacted:
            self._result.add_diagnostic(
                DiagnosticSeverity.INFO,
                f"label value(s) redacted: {', '.join(sorted(redacted))}",
                self._file.path,
                location.line,
                "dockerfile",
            )

    def _runtime(
        self, instruction: str, argument: str, location: SourceLocation
    ) -> None:
        """Record runtime configuration as an attribute of the current stage."""

        if not self._current_stage_id:
            return

        # Truncated: the value is recorded as configuration, not executed, and
        # a long shell snippet would bloat the report.
        value = argument[:_MAX_ARGUMENT_LENGTH]
        key = instruction.lower()

        for resource in self._result.resources:
            if resource.id == self._current_stage_id:
                resource.attributes[key] = value
                break

    def _copy(self, instruction: str, argument: str, location: SourceLocation) -> None:
        """Record build inputs, resolving `--from` against declared stages."""

        tokens = argument.split()
        from_stage: str | None = None
        sources: list[str] = []

        for token in tokens:
            if token.startswith("--from="):
                from_stage = token.split("=", 1)[1]
                continue

            if token.startswith("--") or token.startswith("["):
                # Other flags (--chown, --chmod) and the JSON array form carry no
                # path information we need here.
                continue

            sources.append(token)

        # The final token is the destination, not an input.
        sources = sources[:-1] if len(sources) > 1 else []

        if from_stage:
            self._copy_from_stage(from_stage, location)

        for source in sources:
            self._copy_source(instruction, source, location)

    def _copy_from_stage(self, stage: str, location: SourceLocation) -> None:
        """Resolve a `COPY --from` target against the file's own stages."""

        target_id = self._stages.get(stage)
        resolved = target_id is not None

        self._result.references.append(
            ResourceReference(
                id=reference_id(
                    self._file.path,
                    ReferenceKind.BUILD_STAGE,
                    stage,
                    "dockerfile_copy_from",
                ),
                kind=ReferenceKind.BUILD_STAGE,
                name=stage,
                location=location,
                status=(
                    ReferenceStatus.RESOLVED if resolved else ReferenceStatus.UNRESOLVED
                ),
                reference_type="dockerfile_copy_from",
                target_id=target_id,
                reason=None if resolved else "stage is not declared in this file",
                evidence=[
                    ExtractedEvidence(
                        "dockerfile_copy_from",
                        f"build input is copied from the stage '{stage}'",
                        ExtractionMethod.DOCKERFILE,
                        location,
                    )
                ],
            )
        )

        if resolved and self._current_stage_id:
            self._add_relationship(
                RelationshipType.BUILDS_FROM,
                RelationshipOrigin.DECLARED_BUILD_INPUT,
                self._current_stage_id,
                target_id,
                location,
                True,
                f"build input is copied from the stage '{stage}'",
            )

    def _copy_source(
        self, instruction: str, source: str, location: SourceLocation
    ) -> None:
        """Record a copied source path as a build input."""

        if source in ("--",):
            return

        key = f"{instruction}:{source}"

        if key in self._declared_files:
            return

        self._declared_files.add(key)

        self._result.references.append(
            ResourceReference(
                id=reference_id(
                    self._file.path,
                    ReferenceKind.FILE,
                    source,
                    "dockerfile_copy_source",
                ),
                kind=ReferenceKind.FILE,
                name=source,
                location=location,
                status=ReferenceStatus.UNRESOLVED,
                reference_type="dockerfile_copy_source",
                reason=(
                    "build input path is relative to the build context and needs "
                    "the inventory to resolve"
                ),
                evidence=[
                    ExtractedEvidence(
                        "dockerfile_copy_source",
                        f"{instruction} adds '{source}' to the image",
                        ExtractionMethod.DOCKERFILE,
                        location,
                    )
                ],
            )
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _stage_attribute(self, key: str) -> list:
        """Return a mutable list attribute on the current stage."""

        for resource in self._result.resources:
            if resource.id == self._current_stage_id:
                return resource.attributes.setdefault(key, [])

        # An instruction before any FROM has no stage to attach to.
        return []

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
                        "dockerfile_declaration",
                        detail,
                        ExtractionMethod.DOCKERFILE,
                        location,
                    )
                ],
            )
        )


def _key_value_pairs(argument: str, variables: dict[str, str]) -> list[tuple[str, str]]:
    """Parse `KEY=value KEY2=value2` or the legacy `KEY value` form.

    Docker's own variable substitution is applied for simple `$VAR` and
    `${VAR}` references so a value that is assembled from earlier variables can
    still be recognised as an endpoint.
    """

    if not argument:
        return []

    if "=" not in argument:
        # Legacy `ENV key value` form: everything after the first token is the
        # value, and it is only valid for a single pair.
        key, _, value = argument.partition(" ")
        return [(key.strip(), _expand(value.strip(), variables))] if key else []

    pairs: list[tuple[str, str]] = []
    key = ""
    buffer: list[str] = []

    for token in argument.split():
        if "=" in token:
            if key:
                pairs.append((key, _expand(" ".join(buffer).strip(), variables)))
            key, _, value = token.partition("=")
            buffer = [value]
        else:
            # A continuation of the previous value.
            buffer.append(token)

    if key:
        pairs.append((key, _expand(" ".join(buffer).strip(), variables)))

    return [(item_key, value) for item_key, value in pairs if item_key]


def _expand(value: str, variables: dict[str, str]) -> str:
    """Expand simple `$VAR` and `${VAR}` references using known variables."""

    if "$" not in value:
        return value

    def replace(match: re.Match[str]) -> str:
        name = match.group("braced") or match.group("plain")

        return variables.get(name, match.group(0))

    return re.sub(
        r"\$\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}|\$(?P<plain>[A-Za-z_][A-Za-z0-9_]*)",
        replace,
        value,
    )
