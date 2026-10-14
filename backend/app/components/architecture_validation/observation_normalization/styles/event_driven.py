"""Event-driven style adapter.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Normalises an event-driven architecture.

        This is the adapter that proves the design is genuinely style-agnostic
        rather than microservice code with extra steps.

        An event-driven dependency arrives as two hops through a channel:
        A publishes to a topic, and B subscribes to it. Downstream that has to be
        one relationship - A communicates with B - or every rule about who may
        depend on whom would need an event-driven special case, and the generality
        claim would be empty.

        So the two hops collapse into one fact with the channel kept as an
        attribute. The channel element itself produces no fact: it is how the
        relationship is implemented, not a party to it.

        A publish with no subscriber, or a subscriber with no publisher, is kept as
        a fact against the channel. A topic nobody consumes is a real architectural
        observation, and discarding it would hide it.
"""

from collections import defaultdict

from app.domain.recovered_architecture import (
    ArchitectureStyle,
    ElementKind,
    RecoveredArchitecture,
)

from ...models import ObservedFact, RelationshipKind
from .._identity import fact_id
from .base import base_attributes

PUBLISH_LABELS = frozenset({"publishes", "publish", "produces", "emits", "sends"})
SUBSCRIBE_LABELS = frozenset({"subscribed-by", "subscribes", "consumes", "receives", "listens"})


class EventDrivenAdapter:
    """Collapses publish/subscribe pairs through a channel into one fact."""

    style = ArchitectureStyle.EVENT_DRIVEN

    def normalise(self, architecture: RecoveredArchitecture) -> tuple[ObservedFact, ...]:
        publishers: dict[str, list] = defaultdict(list)
        subscribers: dict[str, list] = defaultdict(list)
        direct = []

        for relationship in architecture.relationships:
            label = relationship.label.strip().lower()
            if label in PUBLISH_LABELS and self._is_channel(architecture, relationship.target_id):
                publishers[relationship.target_id].append(relationship)
            elif label in SUBSCRIBE_LABELS and self._is_channel(
                architecture, relationship.source_id
            ):
                subscribers[relationship.source_id].append(relationship)
            else:
                direct.append(relationship)

        facts = []
        for channel_id in sorted(set(publishers) | set(subscribers)):
            channel = architecture.element_by_id(channel_id)
            channel_name = channel.name if channel else channel_id

            if publishers[channel_id] and subscribers[channel_id]:
                for publication in publishers[channel_id]:
                    for subscription in subscribers[channel_id]:
                        fact = self._collapsed(
                            architecture, publication, subscription, channel_name
                        )
                        if fact:
                            facts.append(fact)
                continue

            # One side only. Reported against the channel, because a topic with
            # no consumer is an observation worth keeping.
            for relationship in publishers[channel_id] + subscribers[channel_id]:
                fact = self._dangling(architecture, relationship, channel_name)
                if fact:
                    facts.append(fact)

        for relationship in direct:
            fact = self._direct(architecture, relationship)
            if fact:
                facts.append(fact)

        return tuple(facts)

    def _is_channel(self, architecture: RecoveredArchitecture, element_id: str) -> bool:
        element = architecture.element_by_id(element_id)
        return element is not None and element.kind is ElementKind.CHANNEL

    def _collapsed(self, architecture, publication, subscription, channel_name):
        publisher = architecture.element_by_id(publication.source_id)
        subscriber = architecture.element_by_id(subscription.target_id)
        if publisher is None or subscriber is None:
            return None

        # The weaker of the two halves wins: a relationship established through
        # one confirmed and one inferred hop is only as good as the inferred one.
        quality = (
            publication.quality
            if publication.quality == subscription.quality
            else "inferred"
        )

        return ObservedFact(
            fact_id=fact_id(
                publisher.name,
                RelationshipKind.COMMUNICATES_WITH,
                subscriber.name,
                architecture.release_id,
            ),
            release_id=architecture.release_id,
            subject=publisher.name,
            relationship=RelationshipKind.COMMUNICATES_WITH,
            object=subscriber.name,
            style_resolved=self.style,
            quality=quality,
            attributes=base_attributes(
                f"{publication.label}->{subscription.label}",
                {
                    "interaction": "async",
                    "via": channel_name,
                    "collapsed_hops": 2,
                    **publication.attributes,
                },
            ),
        )

    def _dangling(self, architecture, relationship, channel_name):
        source = architecture.element_by_id(relationship.source_id)
        target = architecture.element_by_id(relationship.target_id)
        if source is None or target is None:
            return None
        return ObservedFact(
            fact_id=fact_id(
                source.name,
                RelationshipKind.COMMUNICATES_WITH,
                target.name,
                architecture.release_id,
            ),
            release_id=architecture.release_id,
            subject=source.name,
            relationship=RelationshipKind.COMMUNICATES_WITH,
            object=target.name,
            style_resolved=self.style,
            quality=relationship.quality,
            attributes=base_attributes(
                relationship.label,
                {"interaction": "async", "via": channel_name, "unpaired": True},
            ),
        )

    def _direct(self, architecture, relationship):
        source = architecture.element_by_id(relationship.source_id)
        target = architecture.element_by_id(relationship.target_id)
        if source is None or target is None:
            return None
        from .base import classify_label

        kind = classify_label(relationship.label)
        return ObservedFact(
            fact_id=fact_id(source.name, kind, target.name, architecture.release_id),
            release_id=architecture.release_id,
            subject=source.name,
            relationship=kind,
            object=target.name,
            style_resolved=self.style,
            quality=relationship.quality,
            attributes=base_attributes(
                relationship.label,
                {"interaction": relationship.label.lower(), **relationship.attributes},
            ),
        )
