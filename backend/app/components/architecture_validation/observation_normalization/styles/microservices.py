"""Microservices style adapter.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Normalises a microservice architecture.

        The simplest case: recovery already reports one element per service and
        one relationship per declared dependency, so the reduction is mostly
        keeping the transport as an attribute instead of in the relationship name.

        The transport is worth keeping. "Talks over HTTP" and "talks over gRPC"
        validate identically against a rule about who may talk to whom, but the
        distinction matters when the rule is about how.
"""

from app.domain.recovered_architecture import ArchitectureStyle, RecoveredArchitecture

from ...models import ObservedFact
from .base import classify_label, observed_fact


class MicroservicesAdapter:
    """One element per service, one fact per declared dependency."""

    style = ArchitectureStyle.MICROSERVICES

    def normalise(self, architecture: RecoveredArchitecture) -> tuple[ObservedFact, ...]:
        facts = []
        for relationship in architecture.relationships:
            source = architecture.element_by_id(relationship.source_id)
            target = architecture.element_by_id(relationship.target_id)
            if source is None or target is None:
                # A relationship naming an element that is not in the
                # architecture is recovery's inconsistency, not a fact. It is
                # dropped here and counted as a warning by the service, rather
                # than becoming a fact about something that does not exist.
                continue

            facts.append(
                observed_fact(
                    architecture,
                    subject=source,
                    relationship=classify_label(relationship.label),
                    object_=target,
                    style_resolved=self.style,
                    quality=relationship.quality,
                    label=relationship.label,
                    extra={
                        "interaction": relationship.label.lower(),
                        **relationship.attributes,
                    },
                )
            )
        return tuple(facts)
