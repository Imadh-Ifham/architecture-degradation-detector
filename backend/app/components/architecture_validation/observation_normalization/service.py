"""Observation normalization service.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Turns a recovered architecture into one uniform fact shape, whatever style
    it came from.

    Research module: M1.
"""

from dataclasses import replace

from app.domain.recovered_architecture import RecoveredArchitecture

from ..ports import SourceArtifactReader
from ._derivation import ManifestRelationshipDeriver
from .models import NormalizationOutcome
from .styles import GENERIC_STYLE_NAME, adapter_for


class ObservationNormalizationService:
    """Turns a recovered architecture into canonical observed facts."""

    def __init__(self, artifact_reader: SourceArtifactReader | None = None) -> None:
        """Bind the service to a source artifact reader.

        Optional because the reader is only needed to derive relationships the
        recovered architecture did not supply. Once recovery reports them, this
        service needs no filesystem access at all - and passing None then is
        the honest configuration rather than a stub.
        """

        self._artifact_reader = artifact_reader

    def normalise(
        self,
        architecture: RecoveredArchitecture,
        manifest_paths: tuple[str, ...] | None = None,
    ) -> NormalizationOutcome:
        """Normalise a recovered architecture into observed facts.

        Selects a style adapter from the registry and lets it reduce the
        architecture's relationships into the canonical triple. When the
        architecture carries no element-to-element relationships at all, the
        derivation builds them from the deployment manifests recovery has
        already located.

        Downstream subcomponents never learn which style a fact came from,
        which is what lets one validation algorithm serve every style.
        """

        warnings: list[str] = []
        derived_count = 0

        # The architecture carries the paths recovery classified. An explicit
        # argument overrides them, which a test uses; nothing in the pipeline
        # passes one.
        paths = architecture.manifest_paths if manifest_paths is None else manifest_paths

        if not architecture.has_element_relationships:
            architecture, derived_count, derivation_warnings = self._derive(
                architecture, paths
            )
            warnings.extend(derivation_warnings)

        adapter = adapter_for(architecture.style)
        facts = adapter.normalise(architecture)

        style_resolved = getattr(adapter, "style", architecture.style)
        if type(adapter).__name__ == "GenericAdapter":
            style_resolved = GENERIC_STYLE_NAME
            warnings.append(
                "architecture style not resolved; normalised generically and capped"
            )

        dropped = len(architecture.relationships) - len(facts)
        if dropped > 0:
            # Only the event-driven adapter legitimately emits fewer facts than
            # relationships, by collapsing two hops into one. Anywhere else a
            # shortfall means a relationship named an element that is not in
            # the architecture, which is worth saying out loud.
            warnings.append(
                f"{dropped} relationship(s) produced no fact; "
                "either collapsed by the style adapter or naming an unknown element"
            )

        return NormalizationOutcome(
            facts=facts,
            style_resolved=str(style_resolved),
            derived_relationships=derived_count,
            warnings=tuple(warnings),
        )

    def _derive(self, architecture: RecoveredArchitecture, manifest_paths: tuple[str, ...]):
        """Fill in the relationships recovery did not report."""

        if self._artifact_reader is None or not manifest_paths:
            return (
                architecture,
                0,
                (
                    "recovered architecture has no element relationships and they "
                    "could not be derived: no artifact reader or no manifest paths",
                ),
            )

        deriver = ManifestRelationshipDeriver(
            self._artifact_reader, architecture.repository_id, architecture.release_id
        )
        relationships, warnings = deriver.derive(architecture.elements, manifest_paths)
        return (
            replace(architecture, relationships=relationships),
            len(relationships),
            warnings,
        )
