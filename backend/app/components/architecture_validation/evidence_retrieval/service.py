"""Evidence retrieval service.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Assembles exactly what the model is allowed to reason from, for one fact.

    Research module: M3.
"""

from ..models import EvidencePackage, ObservedFact, Resolution


class EvidenceRetrievalService:
    """Assembles exactly what the model is allowed to reason from, for one fact."""

    def assemble(self, fact: ObservedFact, resolution: Resolution) -> EvidencePackage:
        """Builds the evidence package for one fact.

        Collects the governing rule, its rationale, the record it replaced and
        the fact's immediate structural neighbourhood, each with a span that
        points at a real location.

        Everything is ordered deterministically, because the package's hash is
        both the cache key and the guarantee that two runs over one release
        produce the same question.
        """

        raise NotImplementedError
