"""Analyzer selection.

Author: Imadh Ifham
Date: 2026-10-14
Description:
    Chooses which analyzer handles a given inventory file.

    This is not manifest detection: the inventory has already decided that a
    file is a deployment manifest or an API specification. The registry only
    refines that decision when several analyzers could apply - Compose and
    Kubernetes are both YAML deployment manifests, so the more specific
    filename convention must be offered first.
"""

from typing import Callable

from app.components.architecture_recovery.manifest_analysis.base import (
    ManifestAnalyzer,
)
from app.components.architecture_recovery.manifest_analysis.compose import (
    ComposeAnalyzer,
)
from app.components.architecture_recovery.manifest_analysis.dockerfile import (
    DockerfileAnalyzer,
)
from app.components.architecture_recovery.manifest_analysis.kubernetes import (
    KubernetesAnalyzer,
)
from app.components.architecture_recovery.manifest_analysis.openapi import (
    OpenApiAnalyzer,
)
from app.components.architecture_recovery.manifest_analysis.protobuf import (
    ProtobufAnalyzer,
)
from app.components.architecture_recovery.repository_inventory.models import (
    FileCategory,
    FileRecord,
)


#: Categories whose files are worth analyzing. Everything else - source code,
#: tests, documentation, Terraform, lock files - is ignored by this stage.
CANDIDATE_CATEGORIES: frozenset[FileCategory] = frozenset(
    {FileCategory.DEPLOYMENT_MANIFEST, FileCategory.API_SPECIFICATION}
)

#: Ordered most specific first, because selection is first-match-wins.
#:
#: Each factory states which limits that analyzer actually uses: only the
#: Kubernetes analyzer is multi-document, so only it takes `max_documents`.
DEFAULT_ANALYZER_FACTORIES: tuple[Callable[..., ManifestAnalyzer], ...] = (
    lambda max_bytes, max_documents: DockerfileAnalyzer(max_bytes=max_bytes),
    lambda max_bytes, max_documents: ComposeAnalyzer(max_bytes=max_bytes),
    lambda max_bytes, max_documents: OpenApiAnalyzer(max_bytes=max_bytes),
    lambda max_bytes, max_documents: ProtobufAnalyzer(max_bytes=max_bytes),
    # The fallback for any remaining YAML deployment manifest, so it must come
    # after the analyzers with a more specific filename rule.
    lambda max_bytes, max_documents: KubernetesAnalyzer(
        max_bytes=max_bytes, max_documents=max_documents
    ),
)


class AnalyzerRegistry:
    """Selects the analyzer responsible for a file."""

    def __init__(
        self,
        analyzers: tuple[ManifestAnalyzer, ...] | None = None,
        max_bytes: int = 1_048_576,
        max_documents: int = 64,
    ) -> None:
        """Build the registry, or accept an explicit analyzer list.

        An explicit list is how tests substitute a stub analyzer, and how a
        future format is added without touching the service.
        """

        self._analyzers: tuple[ManifestAnalyzer, ...] = (
            analyzers
            if analyzers is not None
            else tuple(
                factory(max_bytes=max_bytes, max_documents=max_documents)
                for factory in DEFAULT_ANALYZER_FACTORIES
            )
        )

    def select(self, file: FileRecord) -> ManifestAnalyzer | None:
        """Return the first analyzer that accepts the file, if any."""

        for analyzer in self._analyzers:
            if analyzer.can_analyze(file):
                return analyzer

        return None

    def names(self) -> list[str]:
        """Return the registered analyzer names, for the report's options."""

        return [analyzer.name for analyzer in self._analyzers]

    @staticmethod
    def is_candidate(file: FileRecord) -> bool:
        """Report whether a file is relevant to manifest analysis at all."""

        return file.category in CANDIDATE_CATEGORIES
