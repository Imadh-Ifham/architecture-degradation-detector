"""Relationship discovery.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Records potential relationships between files and candidate components.
    Every relationship carries the evidence that produced it and is marked
    either `confirmed` (an artifact names the association) or `inferred`
    (structure suggests it), so a consumer can tell a fact from a hypothesis.

    Relationships are candidates, not assertions: later stages are expected to
    promote, demote or discard them.
"""

import re
from hashlib import sha1
from pathlib import PurePosixPath

from app.components.architecture_recovery.repository_inventory.components import (
    find_component_by_name,
    is_within,
    parent_directory,
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
    Relationship,
    RelationshipType,
)

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


def relationship_id(
    relationship_type: RelationshipType, source_id: str, target_id: str
) -> str:
    """Derive a deterministic relationship id from its endpoints."""

    digest = sha1(
        f"{relationship_type.value}:{source_id}:{target_id}".encode("utf-8")
    ).hexdigest()[:12]
    return f"relationship:{digest}"


def path_tokens(relative_path: str) -> set[str]:
    """Split a path into lowercase alphanumeric tokens.

    Used to look for a component's name in a file path, for example matching
    component `cart` against `specs/cart.yaml`.
    """

    name = PurePosixPath(relative_path).name
    stem = name.rsplit(".", 1)[0] if "." in name else name

    return {token for token in _TOKEN_SPLIT.split(stem.lower()) if token}


class RelationshipBuilder:
    """Builds the relationship collection for an inventory."""

    def build(
        self,
        files: list[FileRecord],
        components: list[CandidateComponent],
        analyses: dict[str, ManifestAnalysis],
    ) -> list[Relationship]:
        """Return every relationship discovered in the scanned repository."""

        collected: dict[str, Relationship] = {}
        by_id = {component.id: component for component in components}

        for file in files:
            self._add_file_membership(file, by_id, collected)

        self._add_build_manifest_links(files, by_id, collected)
        self._add_deployment_links(files, components, analyses, collected)
        self._add_api_spec_links(files, components, collected)
        self._add_test_links(files, by_id, collected)

        return sorted(
            collected.values(),
            key=lambda item: (item.type.value, item.source_id, item.target_id),
        )

    @staticmethod
    def _record(
        collected: dict[str, Relationship],
        relationship_type: RelationshipType,
        source_id: str,
        target_id: str,
        confidence: Confidence,
        evidence: list[Evidence],
    ) -> None:
        """Add a relationship, keyed by id so duplicates collapse."""

        identifier = relationship_id(relationship_type, source_id, target_id)

        if identifier in collected:
            return

        collected[identifier] = Relationship(
            id=identifier,
            type=relationship_type,
            source_kind="file",
            source_id=source_id,
            target_kind="component",
            target_id=target_id,
            confidence=confidence,
            evidence=evidence,
        )

    def _add_file_membership(
        self,
        file: FileRecord,
        by_id: dict[str, CandidateComponent],
        collected: dict[str, Relationship],
    ) -> None:
        """Link each assigned file to its component.

        Membership is path-based, so it inherits the component's own strength:
        definite under a manifest-confirmed unit, a candidate under a guessed
        directory group.
        """

        if file.component_id is None:
            return

        component = by_id.get(file.component_id)

        if component is None:
            return

        # A manifest-confirmed component makes containment a certainty; under a
        # directory group it remains a structural guess.
        confidence = (
            Confidence.CONFIRMED
            if component.confidence is Confidence.CONFIRMED
            else Confidence.INFERRED
        )

        self._record(
            collected,
            RelationshipType.FILE_IN_COMPONENT,
            file.id,
            component.id,
            confidence,
            [
                Evidence(
                    "path_prefix",
                    f"file lies under the '{component.root_path}' component root",
                    file.path,
                )
            ],
        )

    def _add_build_manifest_links(
        self,
        files: list[FileRecord],
        by_id: dict[str, CandidateComponent],
        collected: dict[str, Relationship],
    ) -> None:
        """Link a build manifest to the unit it defines."""

        for file in files:
            if file.category is not FileCategory.BUILD_MANIFEST:
                continue

            root = parent_directory(file.path)

            for component in by_id.values():
                if (
                    component.kind is ComponentKind.BUILD_UNIT
                    and component.root_path == root
                ):
                    self._record(
                        collected,
                        RelationshipType.MANIFEST_DEFINES_COMPONENT,
                        file.id,
                        component.id,
                        Confidence.CONFIRMED,
                        [
                            Evidence(
                                "build_manifest",
                                "build manifest defines this unit",
                                file.path,
                            )
                        ],
                    )
                    break

    def _add_deployment_links(
        self,
        files: list[FileRecord],
        components: list[CandidateComponent],
        analyses: dict[str, ManifestAnalysis],
        collected: dict[str, Relationship],
    ) -> None:
        """Link a deployment manifest to each service it declares."""

        for file in files:
            if file.category is not FileCategory.DEPLOYMENT_MANIFEST:
                continue

            analysis = analyses.get(file.id)

            if analysis is None:
                continue

            for service_name in analysis.service_names:
                component = find_component_by_name(components, service_name)

                if component is None:
                    continue

                inside = is_within(file.path, component.root_path)

                self._record(
                    collected,
                    RelationshipType.DEPLOYMENT_REFERENCES_COMPONENT,
                    file.id,
                    component.id,
                    # A deployment manifest living inside the component it names
                    # is direct evidence; a name-only match is not.
                    Confidence.CONFIRMED if inside else Confidence.INFERRED,
                    [
                        Evidence(
                            "deployment_manifest"
                            if inside
                            else "name_match",
                            (
                                f"manifest deploys '{service_name}' and sits inside "
                                "this component's root"
                                if inside
                                else f"manifest declares a service named '{service_name}'"
                            ),
                            file.path,
                        )
                    ],
                )

    def _add_api_spec_links(
        self,
        files: list[FileRecord],
        components: list[CandidateComponent],
        collected: dict[str, Relationship],
    ) -> None:
        """Associate an API specification with a component it names in its path."""

        for file in files:
            if file.category is not FileCategory.API_SPECIFICATION:
                continue

            tokens = path_tokens(file.path)

            for component in components:
                if component.kind is ComponentKind.DEPLOYMENT_SERVICE:
                    continue

                # Both a path segment and the file stem are considered, so
                # `specs/cart.yaml` and `openapi/cart.yaml` both match.
                if component.name.lower() not in tokens:
                    continue

                self._record(
                    collected,
                    RelationshipType.API_SPEC_DESCRIBES_COMPONENT,
                    file.id,
                    component.id,
                    Confidence.INFERRED,
                    [
                        Evidence(
                            "api_spec_name",
                            f"path names the component '{component.name}'",
                            file.path,
                        )
                    ],
                )

    def _add_test_links(
        self,
        files: list[FileRecord],
        by_id: dict[str, CandidateComponent],
        collected: dict[str, Relationship],
    ) -> None:
        """Link a test file to the component that contains it."""

        for file in files:
            if file.category is not FileCategory.TEST or file.component_id is None:
                continue

            if file.component_id not in by_id:
                continue

            self._record(
                collected,
                RelationshipType.TEST_TARGETS_COMPONENT,
                file.id,
                file.component_id,
                Confidence.INFERRED,
                [
                    Evidence(
                        "path_prefix",
                        "test file lies inside the component's root",
                        file.path,
                    )
                ],
            )
