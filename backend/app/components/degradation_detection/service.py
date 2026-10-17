"""C3 orchestration: the only way into the degradation detection component.

Pipeline (docs/implementation-plan.md Section 2.2): ingestion -> detection -> tracking ->
trends -> events. Subcomponents never import each other; this service passes artifacts
between them.
"""


class DegradationDetectionService:
    def run(self, system_id: str) -> None:
        """Analyse every ingested release of one system and export degradation events."""
        raise NotImplementedError("orchestration is built in T-13")
