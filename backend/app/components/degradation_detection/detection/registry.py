"""M2 step 4: the detector registry, the ONLY place in C3 that acts on ``architecture_style``.

C3 has one generic core [locked decision 5]. What is specific to a style is which anti-patterns
make sense for it, and that lives in two places: each detector declares the styles it applies to
(``styles``), and the catalog (``configs/catalog.yaml``) enables detectors per style. This module
joins the two for a release; ``tests/.../test_style_agnostic.py`` fails if any other module reads
the style.

A detector whose ``required_fields`` the release lacks is skipped with ``CATALOG_INPUT_MISSING``
and the others still run: a microservices system without ``datastore_access`` still gets the
universal tier.
"""

from collections.abc import Iterable, Mapping, Sequence

import structlog

from app.components.degradation_detection.config import ALL_STYLES, CatalogConfig
from app.components.degradation_detection.detection.microservices import MICROSERVICES_DETECTORS
from app.components.degradation_detection.detection.models import (
    CATALOG_INPUT_MISSING,
    AntiPatternDetector,
)
from app.components.degradation_detection.detection.universal import UNIVERSAL_DETECTORS
from app.domain.canonical_release import CanonicalRelease

log = structlog.get_logger(__name__)

# Every detector C3 has, in output order.
ALL_DETECTORS: tuple[AntiPatternDetector, ...] = (*UNIVERSAL_DETECTORS, *MICROSERVICES_DETECTORS)

DATASTORE_ACCESS = "datastore_access"
DELEGATION = "delegation"
LAYER = "layer"

__all__ = ["ALL_DETECTORS", "CATALOG_INPUT_MISSING", "DetectorRegistry", "available_fields"]


def available_fields(release: CanonicalRelease) -> frozenset[str]:
    """The optional package fields this release supplies, as ``required_fields`` names them.

    A field sent empty is supplied: C2 looked and found nothing. ``layer`` counts only when every
    element has one, because a layered detector on a half-layered graph would miss or invent
    violations.
    """
    fields = set()
    if release.datastore_access is not None:
        fields.add(DATASTORE_ACCESS)
    if release.delegation is not None:
        fields.add(DELEGATION)
    if release.elements and all(e.layer is not None for e in release.elements):
        fields.add(LAYER)
    return frozenset(fields)


class DetectorRegistry:
    """Chooses the detectors for a release from its style and the fields it supplies."""

    def __init__(
        self, detectors: Iterable[AntiPatternDetector], enabled: Mapping[str, Sequence[str]]
    ) -> None:
        self._detectors: dict[str, AntiPatternDetector] = {}
        for detector in detectors:
            if detector.id in self._detectors:
                raise ValueError(f"detector {detector.id!r} is registered twice")
            self._detectors[detector.id] = detector
        for style, ids in enabled.items():
            for detector_id in ids:
                _check_applies(self._detectors.get(detector_id), detector_id, style)
        self._enabled = {style: frozenset(ids) for style, ids in enabled.items()}

    @classmethod
    def from_catalog(cls, catalog: CatalogConfig) -> "DetectorRegistry":
        return cls(ALL_DETECTORS, catalog.enabled)

    @property
    def detector_ids(self) -> tuple[str, ...]:
        """Every detector the catalog enables for some style, in output order."""
        return tuple(detector.id for detector in self.detectors)

    @property
    def detectors(self) -> tuple[AntiPatternDetector, ...]:
        """Every detector the catalog enables for some style, in output order."""
        enabled = set().union(*self._enabled.values())
        return tuple(d for d in self._detectors.values() if d.id in enabled)

    def for_release(self, release: CanonicalRelease) -> tuple[AntiPatternDetector, ...]:
        return self.detectors_for(
            release.architecture_style, available_fields(release), release_id=release.release_id
        )

    def detectors_for(
        self, style: str, available: frozenset[str], release_id: str | None = None
    ) -> tuple[AntiPatternDetector, ...]:
        """Detectors enabled for ``"*"`` or this style whose required fields are all available."""
        enabled = self._enabled.get(ALL_STYLES, frozenset()) | self._enabled.get(style, frozenset())
        runnable = []
        for detector in self._detectors.values():
            if detector.id not in enabled:
                continue
            missing = detector.required_fields - available
            if missing:
                log.info(
                    "detector_skipped",
                    reason=CATALOG_INPUT_MISSING,
                    detector=detector.id,
                    missing=sorted(missing),
                    style=str(style),
                    release_id=release_id,
                )
                continue
            runnable.append(detector)
        return tuple(runnable)


def _check_applies(detector: AntiPatternDetector | None, detector_id: str, style: str) -> None:
    if detector is None:
        raise ValueError(f"catalog enables unknown detector {detector_id!r} for {style!r}")
    if ALL_STYLES not in detector.styles and style not in detector.styles:
        raise ValueError(
            f"catalog enables {detector_id!r} for {style!r}, but it does not apply there "
            f"(styles: {sorted(detector.styles)})"
        )
