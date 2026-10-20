"""The recovery pipeline's stages, in the order the transport runs them.

Author: Imadh Ifham
Date: 2026-10-20
Description:
    One description of the pipeline, so a reader never has to keep its own
    copy. The stage order already lives in the API layer, which composes the
    subcomponents; this states what each one is for, what it reads and what it
    writes, and the composition root uses it to label the records it makes.

    The subcomponents stay independent and know nothing about this module: it
    describes them from outside, exactly as the validation component describes
    its own stages in `pipeline.py`.
"""

from dataclasses import dataclass

ARTIFACT_INVENTORY = "repository_inventory.json"
ARTIFACT_MANIFEST = "manifest_analysis.json"
ARTIFACT_DISCOVERY = "component_discovery.json"
ARTIFACT_DEPENDENCY = "dependency_resolution.json"
ARTIFACT_SOURCE = "source_code_analysis.json"
ARTIFACT_GRAPH = "architecture_graph_construction.json"


@dataclass(frozen=True)
class RecoveryStage:
    """One stage of architecture recovery, described for a reader."""

    name: str
    order: int
    role: str
    reads: str
    artifact: str | None
    artifact_role: str | None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "order": self.order,
            "role": self.role,
            "reads": self.reads,
            "artifact": self.artifact,
            "artifact_role": self.artifact_role,
        }


RECOVERY_STAGES: tuple[RecoveryStage, ...] = (
    RecoveryStage(
        name="repository_inventory",
        order=1,
        role=(
            "Walks the working tree without reading it: records every file, "
            "classifies it, and proposes the candidate components the tree "
            "implies."
        ),
        reads="the cloned working tree",
        artifact=ARTIFACT_INVENTORY,
        artifact_role=(
            "every file with its classification, plus the candidate components "
            "and the relationships between them"
        ),
    ),
    RecoveryStage(
        name="manifest_analysis",
        order=2,
        role=(
            "Parses the build and deployment manifests the inventory found, "
            "extracting services, ports, endpoints and declared dependencies."
        ),
        reads="the inventory's classified manifests",
        artifact=ARTIFACT_MANIFEST,
        artifact_role=(
            "resources, endpoints, API operations and the relationships the "
            "manifests declare"
        ),
    ),
    RecoveryStage(
        name="component_discovery",
        order=3,
        role=(
            "Turns candidate artifacts into named components, associating each "
            "manifest with the source project that owns it."
        ),
        reads="the inventory and the manifest analysis",
        artifact=ARTIFACT_DISCOVERY,
        artifact_role=(
            "the components, the artifacts that identified each one, and the "
            "rules that associated them"
        ),
    ),
    RecoveryStage(
        name="dependency_resolution",
        order=4,
        role=(
            "Resolves configured endpoints and declared dependencies onto the "
            "components they name, keeping the evidence and refusing to guess."
        ),
        reads="the discovery report and the manifest analysis",
        artifact=ARTIFACT_DEPENDENCY,
        artifact_role=(
            "resolved relationships with their evidence, and every reference "
            "that was unresolved or ambiguous"
        ),
    ),
    RecoveryStage(
        name="source_code_analysis",
        order=5,
        role=(
            "Reads source files for inter-service calls, so a dependency is not "
            "assumed from configuration alone."
        ),
        reads="the inventory, the discovery report and the resolved dependencies",
        artifact=ARTIFACT_SOURCE,
        artifact_role=(
            "source-level findings with file, line and strength, and the "
            "references the code names but the architecture does not contain"
        ),
    ),
    RecoveryStage(
        name="graph_construction",
        order=6,
        role=(
            "Merges the evidence into one version-scoped architecture snapshot "
            "and publishes it to the graph store."
        ),
        reads="the discovery, dependency and source reports",
        artifact=ARTIFACT_GRAPH,
        artifact_role=(
            "the constructed snapshot: its elements, relationships, unresolved "
            "references and diagnostics, as written"
        ),
    ),
)

STAGE_BY_NAME = {stage.name: stage for stage in RECOVERY_STAGES}

__all__ = [
    "RECOVERY_STAGES",
    "RecoveryStage",
    "STAGE_BY_NAME",
]
