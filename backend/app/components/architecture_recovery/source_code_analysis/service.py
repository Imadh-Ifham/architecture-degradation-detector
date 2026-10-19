"""Source code analysis service.

Author: Imadh Ifham
Date: 2026-10-19
Description:
    Orchestrates source code analysis: select eligible source files from the
    inventory, map them to discovered components, scan them with the
    language-scoped patterns, resolve targets through component discovery and
    dependency resolution, and write one report.

    The stage does not clone repositories, re-run inventory, re-parse manifests
    or redo component discovery. It reads the working tree only for the source
    files the inventory already selected.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.components.architecture_recovery.component_discovery.models import (
    ComponentDiscoveryReport,
)
from app.components.architecture_recovery.component_discovery.paths import (
    is_within,
)
from app.components.architecture_recovery.component_discovery.writer import (
    COMPONENT_DISCOVERY_FILE_NAME,
    load_component_discovery,
)
from app.components.architecture_recovery.dependency_resolution.models import (
    DependencyResolutionReport,
)
from app.components.architecture_recovery.dependency_resolution.writer import (
    DEPENDENCY_RESOLUTION_FILE_NAME,
    load_dependency_resolution,
)
from app.components.architecture_recovery.manifest_analysis.models import (
    Diagnostic,
    DiagnosticSeverity,
)
from app.components.architecture_recovery.manifest_analysis.service import (
    AnalysisInputError,
    load_inventory,
)
from app.components.architecture_recovery.repository_inventory.models import (
    FileCategory,
    RepositoryInventory,
    RepositoryRef,
)
from app.components.architecture_recovery.repository_inventory.writer import (
    INVENTORY_FILE_NAME,
)
from app.components.architecture_recovery.source_code_analysis.errors import (
    SourceCodeAnalysisInputError,
)
from app.components.architecture_recovery.source_code_analysis.models import (
    LIMITATIONS,
    STRENGTH_SEMANTICS,
    EvidenceStrength,
    FindingType,
    ResolutionStatus,
    SourceCandidate,
    SourceCodeAnalysisReport,
    SourceCodeAnalysisSummary,
    SourceEvidence,
    SourceFinding,
    SourceLanguage,
    candidate_id,
    finding_id,
)
from app.components.architecture_recovery.source_code_analysis.patterns import (
    MAX_SOURCE_BYTES,
    RawEvidence,
    ScanResult,
    language_for,
    scan_source,
    skip_reason,
)
from app.components.architecture_recovery.source_code_analysis.resolution import (
    ComponentRef,
    DependencyCandidateLink,
    DependencyLink,
    ResolutionResult,
    TargetIndex,
)
from app.components.architecture_recovery.source_code_analysis.writer import (
    write_source_code_analysis,
)
from app.domain.repository import IngestedRepository

_STRENGTH_ORDER: dict[EvidenceStrength, int] = {
    EvidenceStrength.SYMBOL_REFERENCE: 1,
    EvidenceStrength.CLIENT_CONSTRUCTION: 2,
    EvidenceStrength.OBSERVED_INVOCATION: 3,
}

_SUPPORTED_LANGUAGES = (
    SourceLanguage.GO,
    SourceLanguage.PYTHON,
    SourceLanguage.CSHARP,
    SourceLanguage.JAVASCRIPT,
    SourceLanguage.TYPESCRIPT,
    SourceLanguage.JAVA,
)


@dataclass
class _FindingDraft:
    """A resolved finding being accumulated across call sites."""

    finding_type: FindingType
    source_component_id: str
    target_component_id: str
    target_reference: str
    resolution_method: str | None
    evidence_strength: EvidenceStrength
    language: SourceLanguage
    evidence: list[SourceEvidence] = field(default_factory=list)


@dataclass
class _CandidateDraft:
    """An unresolved or ambiguous source observation."""

    finding_type: FindingType
    source_component_id: str
    status: ResolutionStatus
    target_reference: str
    reason: str
    resolution_method: str | None
    evidence_strength: EvidenceStrength
    language: SourceLanguage
    candidate_component_ids: set[str] = field(default_factory=set)
    evidence: list[SourceEvidence] = field(default_factory=list)


class SourceCodeAnalysisService:
    """Extracts source-level dependency evidence and writes the report."""

    def analyze(
        self,
        inventory: RepositoryInventory,
        discovery: ComponentDiscoveryReport,
        dependencies: DependencyResolutionReport,
        root: Path,
    ) -> SourceCodeAnalysisReport:
        """Analyze the working tree at `root` using the upstream reports."""

        components = ComponentRef.from_report(discovery)
        links = [
            DependencyLink.from_relationship(relationship)
            for relationship in dependencies.relationships
        ]
        candidates = [
            DependencyCandidateLink.from_candidate(candidate)
            for candidate in [*dependencies.unresolved, *dependencies.ambiguous]
        ]

        return self._analyze_inputs(
            inventory=inventory,
            components=components,
            links=links,
            candidates=candidates,
            repository=dependencies.repository,
            root=root,
        )

    def run(
        self,
        inventory: RepositoryInventory,
        discovery: ComponentDiscoveryReport,
        dependencies: DependencyResolutionReport,
        root: Path,
        output_directory: Path,
    ) -> tuple[Path, SourceCodeAnalysisReport]:
        """Analyze and write the report into `output_directory`."""

        report = self.analyze(inventory, discovery, dependencies, root)
        path = write_source_code_analysis(report, output_directory)

        return path, report

    def run_for_ingested(
        self, repository: IngestedRepository
    ) -> tuple[Path, SourceCodeAnalysisReport]:
        """Analyze an ingested repository from its existing artifacts."""

        workspace = repository.path.parent

        try:
            inventory = load_inventory(workspace / INVENTORY_FILE_NAME)
        except AnalysisInputError as error:
            raise SourceCodeAnalysisInputError(str(error)) from error

        try:
            component_document = load_component_discovery(
                workspace / COMPONENT_DISCOVERY_FILE_NAME
            )
        except (OSError, ValueError) as error:
            raise SourceCodeAnalysisInputError(
                f"No readable component discovery at "
                f"'{workspace / COMPONENT_DISCOVERY_FILE_NAME}'; run component "
                f"discovery first: {error}"
            ) from error

        try:
            dependency_document = load_dependency_resolution(
                workspace / DEPENDENCY_RESOLUTION_FILE_NAME
            )
        except (OSError, ValueError) as error:
            raise SourceCodeAnalysisInputError(
                f"No readable dependency resolution at "
                f"'{workspace / DEPENDENCY_RESOLUTION_FILE_NAME}'; run "
                f"dependency resolution first: {error}"
            ) from error

        if not isinstance(component_document, dict) or not isinstance(
            dependency_document, dict
        ):
            raise SourceCodeAnalysisInputError(
                "The component discovery and dependency resolution artifacts "
                "must be JSON objects."
            )

        try:
            components = ComponentRef.from_document(component_document)
            links = [
                DependencyLink.from_document(item)
                for item in dependency_document.get("relationships") or []
                if isinstance(item, dict)
            ]
            candidates = [
                DependencyCandidateLink.from_document(item)
                for item in [
                    *(dependency_document.get("unresolved") or []),
                    *(dependency_document.get("ambiguous") or []),
                ]
                if isinstance(item, dict)
            ]
        except (KeyError, TypeError, ValueError) as error:
            raise SourceCodeAnalysisInputError(
                f"An upstream artifact has an unexpected structure: {error}"
            ) from error

        report = self._analyze_inputs(
            inventory=inventory,
            components=components,
            links=links,
            candidates=candidates,
            repository=inventory.repository,
            root=repository.path,
        )
        path = write_source_code_analysis(report, workspace)

        return path, report

    # ------------------------------------------------------------------ #
    # Core analysis
    # ------------------------------------------------------------------ #

    def _analyze_inputs(
        self,
        *,
        inventory: RepositoryInventory,
        components: list[ComponentRef],
        links: list[DependencyLink],
        candidates: list[DependencyCandidateLink],
        repository: RepositoryRef,
        root: Path,
    ) -> SourceCodeAnalysisReport:
        """Run the analysis over the selected source files."""

        index = TargetIndex(components, links, candidates)
        ownership = _Ownership(components)
        root = Path(root)

        findings: dict[tuple, _FindingDraft] = {}
        candidates_by_key: dict[tuple, _CandidateDraft] = {}
        diagnostics: list[Diagnostic] = []
        diagnostic_keys: set[tuple] = set()
        skipped: dict[str, int] = {}
        unsupported: dict[str, int] = {}
        analyzed_components: set[str] = set()
        analyzed_files = 0
        by_language: dict[str, int] = {}
        scans: list[tuple[str, SourceLanguage, ScanResult]] = []
        component_env_keys: dict[str, dict[str, str]] = {}

        for file in sorted(inventory.files, key=lambda item: item.path):
            if file.category is not FileCategory.SOURCE_CODE:
                continue

            reason = skip_reason(file.path, file.category.value)

            if reason:
                skipped[reason] = skipped.get(reason, 0) + 1
                continue

            language = language_for(file.path, file.language)

            if language is SourceLanguage.UNKNOWN:
                unsupported[file.language or file.extension or "unknown"] = (
                    unsupported.get(file.language or file.extension or "unknown", 0)
                    + 1
                )
                continue

            component_id = ownership.component_for(file.path, file.component_id)

            if component_id is None:
                skipped["unowned_source_file"] = skipped.get("unowned_source_file", 0) + 1
                continue

            if file.size_bytes > MAX_SOURCE_BYTES:
                _add_diagnostic(
                    diagnostics,
                    diagnostic_keys,
                    DiagnosticSeverity.WARNING,
                    "source file exceeds the analysis size cap and was skipped",
                    file.path,
                )
                skipped["oversized_source_file"] = (
                    skipped.get("oversized_source_file", 0) + 1
                )
                continue

            try:
                text = (root / file.path).read_text(encoding="utf-8", errors="replace")
            except OSError as error:
                _add_diagnostic(
                    diagnostics,
                    diagnostic_keys,
                    DiagnosticSeverity.WARNING,
                    f"source file could not be read: {error}",
                    file.path,
                )
                skipped["unreadable_source_file"] = (
                    skipped.get("unreadable_source_file", 0) + 1
                )
                continue

            analyzed_files += 1
            analyzed_components.add(component_id)
            by_language[language.value] = by_language.get(language.value, 0) + 1

            scan = scan_source(file.path, language, text)
            scans.append((component_id, language, scan))
            component_env_keys.setdefault(component_id, {}).update(scan.env_keys)

        # Resolve after every file has been scanned so an environment mapping in
        # one file (for example main.go) is available to a call site in another
        # file of the same component (for example handlers.go).
        for component_id, _language, scan in scans:
            merged_scan = ScanResult(
                evidence=scan.evidence,
                env_keys={
                    **component_env_keys.get(component_id, {}),
                    **scan.env_keys,
                },
                assignments=scan.assignments,
            )

            for raw in merged_scan.evidence:
                self._record(
                    raw=raw,
                    scan=merged_scan,
                    source_component_id=component_id,
                    index=index,
                    findings=findings,
                    candidates=candidates_by_key,
                    diagnostics=diagnostics,
                    diagnostic_keys=diagnostic_keys,
                )

        for reason, count in sorted(skipped.items()):
            _add_diagnostic(
                diagnostics,
                diagnostic_keys,
                DiagnosticSeverity.INFO,
                f"{count} source file(s) skipped: {reason}",
            )

        for language, count in sorted(unsupported.items()):
            _add_diagnostic(
                diagnostics,
                diagnostic_keys,
                DiagnosticSeverity.INFO,
                f"{count} source file(s) in unsupported language '{language}' were skipped",
            )

        if not components:
            _add_diagnostic(
                diagnostics,
                diagnostic_keys,
                DiagnosticSeverity.WARNING,
                "no discovered components are available for source code analysis",
            )

        if analyzed_files == 0:
            _add_diagnostic(
                diagnostics,
                diagnostic_keys,
                DiagnosticSeverity.INFO,
                "no eligible source files were analysed",
            )

        resolved = self._assemble_findings(findings, index)
        unresolved, ambiguous = self._assemble_candidates(candidates_by_key, index)
        diagnostics = sorted(
            diagnostics,
            key=lambda item: (item.path, item.line or 0, item.severity.value, item.message),
        )

        return SourceCodeAnalysisReport(
            generated_at=datetime.now(UTC),
            repository=repository,
            options={
                "supported_languages": [language.value for language in _SUPPORTED_LANGUAGES],
                "evidence_strength_semantics": STRENGTH_SEMANTICS,
                "limitations": list(LIMITATIONS),
                "generated_code_policy": (
                    "generated, test, vendored, build-output and standalone client "
                    "files are skipped before scanning"
                ),
                "max_source_bytes": MAX_SOURCE_BYTES,
                "no_graph_write": (
                    "source findings are evidence for a later graph-construction "
                    "stage; this component does not write to Neo4j"
                ),
            },
            summary=_summarise(
                analyzed_components=analyzed_components,
                analyzed_files=analyzed_files,
                skipped_files=sum(skipped.values()),
                resolved=resolved,
                unresolved=unresolved,
                ambiguous=ambiguous,
                diagnostics=diagnostics,
                by_language=by_language,
            ),
            findings=resolved,
            unresolved=unresolved,
            ambiguous=ambiguous,
            diagnostics=diagnostics,
            warnings=[
                diagnostic.message
                for diagnostic in diagnostics
                if diagnostic.severity
                in (DiagnosticSeverity.WARNING, DiagnosticSeverity.ERROR)
            ],
        )

    def _record(
        self,
        *,
        raw: RawEvidence,
        scan: ScanResult,
        source_component_id: str,
        index: TargetIndex,
        findings: dict[tuple, _FindingDraft],
        candidates: dict[tuple, _CandidateDraft],
        diagnostics: list[Diagnostic],
        diagnostic_keys: set[tuple],
    ) -> None:
        """Resolve one raw observation and aggregate it into a finding."""

        resolution = self._resolve(raw, scan, source_component_id, index)
        reference = resolution.target_reference or raw.target_reference

        if (
            len(resolution.target_ids) == 1
            and resolution.target_ids[0] == source_component_id
        ):
            _add_diagnostic(
                diagnostics,
                diagnostic_keys,
                DiagnosticSeverity.INFO,
                (
                    f"source client reference to '{reference}' points at its own "
                    "component and was not recorded as a dependency"
                ),
                raw.path,
                raw.line,
            )
            return

        if len(resolution.target_ids) == 1:
            target_id = resolution.target_ids[0]
            key = (raw.finding_type, source_component_id, target_id)
            draft = findings.get(key)

            if draft is None:
                draft = _FindingDraft(
                    finding_type=raw.finding_type,
                    source_component_id=source_component_id,
                    target_component_id=target_id,
                    target_reference=reference,
                    resolution_method=resolution.method,
                    evidence_strength=raw.strength,
                    language=raw.language,
                )
                findings[key] = draft
            else:
                if _STRENGTH_ORDER[raw.strength] > _STRENGTH_ORDER[draft.evidence_strength]:
                    draft.evidence_strength = raw.strength
                    draft.language = raw.language
                    draft.resolution_method = resolution.method or draft.resolution_method

            _append_evidence(
                draft.evidence,
                _evidence(raw, resolution),
            )
            return

        status = (
            ResolutionStatus.AMBIGUOUS
            if len(resolution.target_ids) > 1
            else ResolutionStatus.UNRESOLVED
        )
        key = (raw.finding_type, source_component_id, status, reference)
        draft = candidates.get(key)

        if draft is None:
            draft = _CandidateDraft(
                finding_type=raw.finding_type,
                source_component_id=source_component_id,
                status=status,
                target_reference=reference,
                reason=resolution.reason or "target could not be resolved",
                resolution_method=resolution.method,
                evidence_strength=raw.strength,
                language=raw.language,
            )
            candidates[key] = draft
        else:
            if _STRENGTH_ORDER[raw.strength] > _STRENGTH_ORDER[draft.evidence_strength]:
                draft.evidence_strength = raw.strength
                draft.language = raw.language

        draft.candidate_component_ids.update(resolution.target_ids)
        _append_evidence(draft.evidence, _evidence(raw, resolution))

    @staticmethod
    def _resolve(
        raw: RawEvidence,
        scan: ScanResult,
        source_component_id: str,
        index: TargetIndex,
    ) -> ResolutionResult:
        """Dispatch resolution by the finding's evidence category."""

        if raw.finding_type is FindingType.GRPC_SERVICE_CALL:
            return index.resolve_service(raw.target_reference, source_component_id)

        if raw.finding_type is FindingType.HTTP_SERVICE_CALL:
            return index.resolve_http(
                raw.expression or raw.target_reference,
                source_component_id,
                scan,
                fallback_reference=raw.target_reference,
            )

        return index.resolve_infrastructure(source_component_id, raw.finding_type)

    def _assemble_findings(
        self,
        findings: dict[tuple, _FindingDraft],
        index: TargetIndex,
    ) -> list[SourceFinding]:
        """Convert finding drafts into serialisable findings."""

        result: list[SourceFinding] = []

        for draft in findings.values():
            result.append(
                SourceFinding(
                    id=finding_id(
                        draft.finding_type,
                        draft.source_component_id,
                        draft.target_component_id,
                    ),
                    finding_type=draft.finding_type,
                    source_component_id=draft.source_component_id,
                    source_component_name=index.component_name(
                        draft.source_component_id
                    ),
                    target_component_id=draft.target_component_id,
                    target_component_name=index.component_name(
                        draft.target_component_id
                    ),
                    status=ResolutionStatus.RESOLVED,
                    evidence_strength=draft.evidence_strength,
                    language=draft.language,
                    target_reference=draft.target_reference,
                    resolution_method=draft.resolution_method,
                    corroborates_dependency_relationship_id=(
                        index.corroborating_relationship(
                            draft.source_component_id, draft.target_component_id
                        )
                    ),
                    evidence=sorted(draft.evidence, key=lambda item: item.sort_key()),
                )
            )

        result.sort(
            key=lambda item: (
                item.finding_type.value,
                item.source_component_name or item.source_component_id,
                item.target_component_name or item.target_component_id,
                item.id,
            )
        )

        return result

    def _assemble_candidates(
        self,
        candidates: dict[tuple, _CandidateDraft],
        index: TargetIndex,
    ) -> tuple[list[SourceCandidate], list[SourceCandidate]]:
        """Convert candidate drafts into unresolved and ambiguous lists."""

        unresolved: list[SourceCandidate] = []
        ambiguous: list[SourceCandidate] = []

        for draft in candidates.values():
            candidate = SourceCandidate(
                id=candidate_id(
                    draft.finding_type,
                    draft.source_component_id,
                    draft.target_reference,
                ),
                finding_type=draft.finding_type,
                source_component_id=draft.source_component_id,
                source_component_name=index.component_name(draft.source_component_id),
                status=draft.status,
                target_reference=draft.target_reference,
                language=draft.language,
                evidence_strength=draft.evidence_strength,
                candidate_component_ids=sorted(draft.candidate_component_ids),
                candidate_component_names=sorted(
                    name
                    for component_id in draft.candidate_component_ids
                    if (name := index.component_name(component_id)) is not None
                ),
                reason=draft.reason,
                resolution_method=draft.resolution_method,
                evidence=sorted(draft.evidence, key=lambda item: item.sort_key()),
            )

            if draft.status is ResolutionStatus.AMBIGUOUS:
                ambiguous.append(candidate)
            else:
                unresolved.append(candidate)

        return (
            sorted(unresolved, key=_candidate_sort_key),
            sorted(ambiguous, key=_candidate_sort_key),
        )


class _Ownership:
    """Maps inventory source files to discovered components."""

    def __init__(self, components: list[ComponentRef]) -> None:
        """Index components by inventory id and ordered root path."""

        self._by_inventory_id = {
            component.inventory_component_id: component
            for component in components
            if component.inventory_component_id
        }
        self._by_root = sorted(
            [component for component in components if component.root_path],
            key=lambda component: (
                len(component.root_path or ""),
                component.root_path or "",
            ),
            reverse=True,
        )

    def component_for(self, path: str, inventory_component_id: str | None) -> str | None:
        """Return the component that owns a repository-relative source path."""

        if inventory_component_id:
            component = self._by_inventory_id.get(inventory_component_id)

            if component is not None and (
                not component.root_path or is_within(path, component.root_path)
            ):
                return component.id

        matches = [
            component
            for component in self._by_root
            if component.root_path and is_within(path, component.root_path)
        ]

        if not matches:
            return None

        deepest = matches[0]
        same_depth = [
            component
            for component in matches[1:]
            if len(component.root_path or "") == len(deepest.root_path or "")
        ]

        if same_depth:
            return None

        return deepest.id


def _candidate_sort_key(item: SourceCandidate) -> tuple:
    """Return a deterministic ordering key for a source candidate."""

    return (
        item.finding_type.value,
        item.source_component_name or item.source_component_id,
        item.target_reference or "",
        item.id,
    )


def _evidence(raw: RawEvidence, resolution: ResolutionResult) -> SourceEvidence:
    """Build serialisable evidence from one raw observation."""

    return SourceEvidence(
        evidence_type=raw.evidence_type,
        strength=raw.strength,
        path=raw.path,
        line=raw.line,
        symbol=raw.symbol,
        method=raw.method,
        detail=raw.detail,
        target_reference=resolution.target_reference or raw.target_reference,
        resolution_method=resolution.method,
        language=raw.language,
    )


def _append_evidence(
    target: list[SourceEvidence], evidence: SourceEvidence
) -> None:
    """Append evidence unless an exact duplicate is already present."""

    key = evidence.sort_key()

    if any(item.sort_key() == key for item in target):
        return

    target.append(evidence)


def _add_diagnostic(
    diagnostics: list[Diagnostic],
    keys: set[tuple],
    severity: DiagnosticSeverity,
    message: str,
    path: str | None = None,
    line: int | None = None,
) -> None:
    """Record a deduplicated diagnostic."""

    key = (severity.value, message, path or "", line or 0)

    if key in keys:
        return

    keys.add(key)
    diagnostics.append(
        Diagnostic(
            severity=severity,
            message=message,
            path=path or "",
            line=line,
            analyzer="source_code_analysis",
        )
    )


def _summarise(
    *,
    analyzed_components: set[str],
    analyzed_files: int,
    skipped_files: int,
    resolved: list[SourceFinding],
    unresolved: list[SourceCandidate],
    ambiguous: list[SourceCandidate],
    diagnostics: list[Diagnostic],
    by_language: dict[str, int],
) -> SourceCodeAnalysisSummary:
    """Compute summary counts from the report's actual contents."""

    by_finding_type: dict[str, int] = {}
    by_evidence_type: dict[str, int] = {}
    evidence_count = 0

    for item in [*resolved, *unresolved, *ambiguous]:
        by_finding_type[item.finding_type.value] = (
            by_finding_type.get(item.finding_type.value, 0) + 1
        )
        evidence_count += len(item.evidence)

        for evidence in item.evidence:
            by_evidence_type[evidence.evidence_type.value] = (
                by_evidence_type.get(evidence.evidence_type.value, 0) + 1
            )

    return SourceCodeAnalysisSummary(
        component_count=len(analyzed_components),
        source_file_count=analyzed_files,
        skipped_file_count=skipped_files,
        finding_count=len(resolved) + len(unresolved) + len(ambiguous),
        resolved_count=len(resolved),
        unresolved_count=len(unresolved),
        ambiguous_count=len(ambiguous),
        corroborated_count=sum(
            1 for finding in resolved if finding.corroborates_dependency_relationship_id
        ),
        evidence_count=evidence_count,
        diagnostic_count=len(diagnostics),
        by_finding_type=dict(sorted(by_finding_type.items())),
        by_evidence_type=dict(sorted(by_evidence_type.items())),
        by_language=dict(sorted(by_language.items())),
    )


def source_code_analysis_service_from_settings() -> SourceCodeAnalysisService:
    """Build a source code analysis service from the application settings.

    The stage currently has no tunable limits beyond its source size cap, so
    this exists to keep the dependency-injection pattern used by the other
    stages.
    """

    return SourceCodeAnalysisService()


__all__ = [
    "SourceCodeAnalysisService",
    "source_code_analysis_service_from_settings",
]
