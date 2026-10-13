"""Candidate component discovery.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Proposes candidate service boundaries from evidence rather than from the
    directory tree alone. Three independent signals are used, in increasing
    order of confidence:

      1. a build manifest declares a name (confirmed),
      2. a directory holds source files but no manifest (inferred candidate),
      3. a deployment manifest names a service (confirmed existence).

    A directory that merely contains code is never asserted to be a service;
    it is offered as an inferred candidate with the evidence that produced it.
"""

from dataclasses import dataclass, field
from hashlib import sha1
from pathlib import PurePosixPath

from app.components.architecture_recovery.repository_inventory.catalog import (
    InventoryOptions,
)
from app.components.architecture_recovery.repository_inventory.manifests import (
    ManifestAnalysis,
)
from app.components.architecture_recovery.repository_inventory.models import (
    CandidateComponent,
    ComponentKind,
    Confidence,
    Evidence,
    FileCategory,
    FileRecord,
)


# Categories whose files indicate that a directory actually contains code.
_CODE_CATEGORIES: frozenset[FileCategory] = frozenset(
    {FileCategory.SOURCE_CODE, FileCategory.TEST}
)

# Preference when several components share a name: a declared build unit is
# stronger evidence than a deployment label or a bare directory.
_NAME_MATCH_PREFERENCE: tuple[ComponentKind, ...] = (
    ComponentKind.BUILD_UNIT,
    ComponentKind.DIRECTORY_GROUP,
    ComponentKind.DEPLOYMENT_SERVICE,
)


def component_id(kind: ComponentKind, key: str) -> str:
    """Derive a deterministic component id from its kind and key.

    Hashing the key keeps ids stable across runs so two inventories of the same
    system can be compared and merged.
    """

    digest = sha1(f"{kind.value}:{key}".encode("utf-8")).hexdigest()[:12]
    return f"component:{digest}"


def is_within(path: str, root: str | None) -> bool:
    """Report whether `path` lies at or below `root`.

    The repository root (".") contains everything. A component with no known
    location (`None`) contains nothing.
    """

    if root is None:
        return False

    if root == ".":
        return True

    return path == root or path.startswith(f"{root}/")


def parent_directory(relative_path: str) -> str:
    """Return the directory holding a repository-relative path.

    Returns "." for a file at the repository root.
    """

    return str(PurePosixPath(relative_path).parent)


def find_component_by_name(
    components: dict[str, CandidateComponent] | list[CandidateComponent], name: str
) -> CandidateComponent | None:
    """Find a component whose name matches, preferring stronger kinds.

    A declared build unit outranks a deployment label, which outranks a bare
    directory, so a name shared by several candidates resolves predictably.
    """

    candidates = components.values() if isinstance(components, dict) else components
    target = name.lower()

    for kind in _NAME_MATCH_PREFERENCE:
        for component in candidates:
            if component.kind is not kind:
                continue

            candidate = component.name.lower()

            # A declared name may be namespaced (a Go module path, a
            # `vendor/package` coordinate), so the last segment is also matched.
            if candidate == target or candidate.rsplit("/", 1)[-1] == target:
                return component

    return None


@dataclass
class ComponentDetectionResult:
    """Candidate components plus the file-to-component assignment."""

    components: list[CandidateComponent] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ComponentDetector:
    """Detects candidate components and assigns files to them."""

    def __init__(self, options: InventoryOptions | None = None) -> None:
        """Bind the detector to a set of scan options."""

        self._options = options or InventoryOptions()

    def detect(
        self,
        files: list[FileRecord],
        analyses: dict[str, ManifestAnalysis],
    ) -> ComponentDetectionResult:
        """Detect candidate components and set `component_id` on each file.

        `analyses` maps a file id to the contents-derived findings for that
        manifest, which is what turns a guessed boundary into a confirmed one.
        """

        components: dict[str, CandidateComponent] = {}
        unit_roots: dict[str, str] = {}
        warnings: list[str] = []

        self._add_build_units(files, analyses, components, unit_roots)
        self._add_directory_groups(files, components, unit_roots)
        self._add_deployment_services(files, analyses, components, warnings)

        ordered = sorted(
            components.values(),
            key=lambda item: (item.root_path or "", item.name.lower(), item.id),
        )

        self._assign_files(files, ordered)

        return ComponentDetectionResult(components=ordered, warnings=warnings)

    def _add_build_units(
        self,
        files: list[FileRecord],
        analyses: dict[str, ManifestAnalysis],
        components: dict[str, CandidateComponent],
        unit_roots: dict[str, str],
    ) -> None:
        """Create one component per directory holding a build manifest."""

        for file in files:
            if file.category is not FileCategory.BUILD_MANIFEST:
                continue

            root = parent_directory(file.path)
            analysis = analyses.get(file.id)
            declared_name = analysis.declared_name if analysis else None

            existing_id = unit_roots.get(root)

            if existing_id is not None:
                # A second manifest in the same directory describes the same
                # unit, so it adds evidence rather than a new component.
                existing = components[existing_id]
                existing.evidence.append(
                    Evidence(
                        "build_manifest",
                        "additional build manifest for the same unit",
                        file.path,
                    )
                )
                if declared_name and existing.confidence is Confidence.INFERRED:
                    existing.name = declared_name
                    existing.confidence = Confidence.CONFIRMED
                    existing.evidence.append(
                        Evidence(
                            "manifest_content",
                            f"manifest declares the name '{declared_name}'",
                            file.path,
                        )
                    )
                continue

            evidence = [
                Evidence(
                    "build_manifest",
                    "build manifest marks this directory as a unit root",
                    file.path,
                )
            ]

            if declared_name:
                evidence.append(
                    Evidence(
                        "manifest_content",
                        f"manifest declares the name '{declared_name}'",
                        file.path,
                    )
                )

            name = declared_name or PurePosixPath(root).name or "root"

            # A build manifest may declare a namespaced name, such as a Go
            # module path. The last segment is the service-like name; the full
            # declared value is kept in the evidence below.
            if "/" in name:
                name = name.rsplit("/", 1)[-1]

            component = CandidateComponent(
                id=component_id(ComponentKind.BUILD_UNIT, root),
                name=name,
                kind=ComponentKind.BUILD_UNIT,
                # Naming the unit is explicit evidence; a manifest we could not
                # read only proves that *some* unit lives here.
                confidence=(
                    Confidence.CONFIRMED if declared_name else Confidence.INFERRED
                ),
                root_path=root,
                evidence=evidence,
            )

            components[component.id] = component
            unit_roots[root] = component.id

    def _add_directory_groups(
        self,
        files: list[FileRecord],
        components: dict[str, CandidateComponent],
        unit_roots: dict[str, str],
    ) -> None:
        """Propose inferred components for directories holding code.

        This is deliberately the weakest signal: the resulting components are
        always `inferred`, because a directory existing is not proof that it is
        a service boundary.
        """

        group_counts: dict[str, int] = {}

        for file in files:
            if file.category not in _CODE_CATEGORIES:
                continue

            segments = PurePosixPath(file.path).parts[:-1]

            if not segments:
                # A file at the repository root belongs to no subdirectory.
                continue

            depth = self._options.grouping_depth

            if len(segments) >= depth:
                root = "/".join(segments[:depth])
            else:
                root = "/".join(segments)

            group_counts[root] = group_counts.get(root, 0) + 1

        for root in sorted(group_counts):
            if root in unit_roots:
                # Already claimed by a build manifest, which is stronger.
                continue

            if any(
                is_within(root, existing_root) and existing_root != "."
                for existing_root in unit_roots
            ):
                # Nested inside a known unit, so it is part of that unit.
                continue

            component = CandidateComponent(
                id=component_id(ComponentKind.DIRECTORY_GROUP, root),
                name=PurePosixPath(root).name,
                kind=ComponentKind.DIRECTORY_GROUP,
                confidence=Confidence.INFERRED,
                root_path=root,
                evidence=[
                    Evidence(
                        "directory_group",
                        "directory holds "
                        f"{group_counts[root]} file(s) that look like source or "
                        "tests but no build manifest",
                        root,
                    )
                ],
            )

            components[component.id] = component

    def _add_deployment_services(
        self,
        files: list[FileRecord],
        analyses: dict[str, ManifestAnalysis],
        components: dict[str, CandidateComponent],
        warnings: list[str],
    ) -> None:
        """Reconcile services declared by deployment manifests with components."""

        for file in files:
            if file.category is not FileCategory.DEPLOYMENT_MANIFEST:
                continue

            analysis = analyses.get(file.id)

            if analysis is None or not analysis.service_names:
                continue

            for service_name in analysis.service_names:
                match = find_component_by_name(components, service_name)

                if match is not None:
                    # A deployment manifest for a unit that sits inside that
                    # unit's own directory is strong evidence for the pairing.
                    if is_within(file.path, match.root_path):
                        match.confidence = Confidence.CONFIRMED
                        match.evidence.append(
                            Evidence(
                                "deployment_manifest",
                                f"deploys '{service_name}' and sits inside this "
                                "component's root",
                                file.path,
                            )
                        )
                    else:
                        # Name agreement only: recorded, but not treated as proof.
                        match.evidence.append(
                            Evidence(
                                "name_match",
                                f"deployment manifest declares a service named "
                                f"'{service_name}'",
                                file.path,
                            )
                        )
                    continue

                deployment_id = component_id(
                    ComponentKind.DEPLOYMENT_SERVICE, service_name.lower()
                )

                if deployment_id in components:
                    continue

                components[deployment_id] = CandidateComponent(
                    id=deployment_id,
                    name=service_name,
                    kind=ComponentKind.DEPLOYMENT_SERVICE,
                    confidence=Confidence.CONFIRMED,
                    # No root path: the manifest names the service but does not
                    # tell us where its code lives, and guessing would be
                    # directory proximity dressed up as evidence.
                    root_path=None,
                    evidence=[
                        Evidence(
                            "deployment_manifest",
                            f"deployment manifest declares the service "
                            f"'{service_name}'",
                            file.path,
                        )
                    ],
                )

                warnings.append(
                    f"deployment manifest '{file.path}' declares service "
                    f"'{service_name}' but no matching code component was found"
                )

    @staticmethod
    def _assign_files(
        files: list[FileRecord], components: list[CandidateComponent]
    ) -> None:
        """Attach each file to the deepest component that contains it."""

        located = [item for item in components if item.root_path is not None]

        for file in files:
            best: CandidateComponent | None = None
            best_depth = -1

            for component in located:
                if not is_within(file.path, component.root_path):
                    continue

                depth = len(component.root_path or "")

                if depth > best_depth:
                    best = component
                    best_depth = depth

            if best is None:
                continue

            file.component_id = best.id
            best.file_count += 1

            if file.language and file.language not in best.languages:
                best.languages.append(file.language)

        for component in components:
            component.languages.sort()
