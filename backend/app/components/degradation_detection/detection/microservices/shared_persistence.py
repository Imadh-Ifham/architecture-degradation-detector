"""SharedPersistence: services that share one datastore (plan Section 4, M2).

Database-per-service is the microservices default; two services that read or write the same
datastore are coupled through its schema, whatever their dependency graph says. One instance per
datastore that two or more elements access. "Shared" means more than one, so the two is part of
the definition, like the two members of a cycle, not a tunable threshold (owner decision, T-07).

Members are the services, not the datastore: the datastore is not an element of the graph. It is
the instance's identity instead (``SharedPersistence:orders_db``), because its users change from
release to release while the datastore does not. Access modes are ignored: a read-only user is
still coupled to the schema.
"""

from app.components.degradation_detection.detection.metric_registry import instance_measure
from app.components.degradation_detection.detection.models import (
    ArchGraph,
    ReleaseContext,
    local_instance_id,
)
from app.components.degradation_detection.models import AntiPatternInstance, MetricDef
from app.domain.degradation_event import Scope

SERVICES_PER_STORE = "services_per_store"


class SharedPersistence:
    id: str = "SharedPersistence"
    catalog: str = "microservices"
    styles: frozenset[str] = frozenset({"microservices"})
    scope: Scope = Scope.INSTANCE
    required_fields: frozenset[str] = frozenset({"datastore_access"})
    driving_metrics: tuple[str, ...] = ()  # degradation is the instance's services_per_store
    instance_measures: tuple[MetricDef, ...] = (instance_measure(SERVICES_PER_STORE, "count"),)

    def detect(self, g: ArchGraph, ctx: ReleaseContext) -> list[AntiPatternInstance]:
        if g.datastore_access is None:  # the registry skips this detector; never guess
            return []
        users: dict[str, set[str]] = {}
        for access in g.datastore_access:
            users.setdefault(access.datastore, set()).add(access.element_id)
        return [
            AntiPatternInstance(
                release_id=g.release_id,
                local_instance_id=local_instance_id(self.id, datastore),
                anti_pattern_type=self.id,
                catalog=self.catalog,
                scope=self.scope,
                members=tuple(sorted(services)),
                measures={SERVICES_PER_STORE: float(len(services))},
            )
            for datastore, services in sorted(users.items())
            if len(services) >= 2
        ]
