"""Relationship derivation from deployment manifests.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Builds element-to-element relationships when the recovered architecture
    arrives without any.

    Recovery currently reports relationships between files and components -
    a file is in one, a manifest defines one - and none between one element and
    another. Validation has nothing to validate without those, so it derives
    them from the deployment manifests recovery has already located and
    classified.

    How: a Kubernetes workload declares the addresses of the services it talks
    to as container environment values, which is how a service in a manifest
    names another service. A value whose host matches a known element is a
    declared dependency between the two.

    What these are, precisely: **declared** dependencies, not observed calls.
    A manifest says a service was configured to reach another one, not that it
    did. The distinction belongs in the output rather than in a footnote, so
    every derived relationship carries `observed: false`.

    Two axes, kept separate. Evidence quality asks whether an artifact names
    the thing, and for a declared address the answer is yes - so these are
    confirmed, in recovery's own sense of the word. Observation mode asks
    whether the call was seen happening, and the answer is no. Collapsing them
    into one field would cap every manifest-derived relationship at review,
    which would leave the component unable to report a violation about any
    repository whose runtime is not instrumented - that is to say, all of
    them.

    This runs only when the architecture has no relationships of its own, so it
    retires itself the day recovery starts reporting them - no flag to
    remember and no code to remove under deadline.
"""

import re

import yaml

from app.domain.recovered_architecture import (
    ArchitectureElement,
    ArchitectureRelationship,
    DerivationMethod,
    EvidenceQuality,
)

from ._identity import canonical_name

_ADDRESS_VALUE = re.compile(
    r"^(?:(?P<scheme>https?|grpc)://)?(?P<host>[a-z0-9][a-z0-9\-.]*)(?::(?P<port>\d{2,5}))?/?$",
    re.IGNORECASE,
)

_ADDRESS_KEY = re.compile(r"(ADDR|ADDRESS|HOST|URL|URI|ENDPOINT|SERVICE)$", re.IGNORECASE)

_PORT_LABELS = {
    "50051": "grpc",
    "8080": "http",
    "80": "http",
    "443": "https",
    "6379": "redis",
    "5432": "postgres",
}


class ManifestRelationshipDeriver:
    """Derives declared dependencies from deployment manifests."""

    def __init__(self, artifact_reader, repository_id: str, release_id: str) -> None:
        """Bind the deriver to one release of one repository.

        The reader is a port, so this class never touches the filesystem and
        can be exercised against in-memory manifests.
        """

        self._reader = artifact_reader
        self._repository_id = repository_id
        self._release_id = release_id

    def derive(
        self,
        elements: tuple[ArchitectureElement, ...],
        manifest_paths: tuple[str, ...],
    ) -> tuple[tuple[ArchitectureRelationship, ...], tuple[str, ...]]:
        """Return the derived relationships and any warnings.

        Warnings are returned rather than logged. A derivation that silently
        skipped an unreadable manifest would under-report the architecture with
        nothing saying so, and an under-reported architecture looks like a
        clean one.
        """

        by_canonical = {canonical_name(element.name): element for element in elements}
        relationships: dict[tuple[str, str], ArchitectureRelationship] = {}
        warnings: list[str] = []

        for path in manifest_paths:
            try:
                text = self._reader.read_text(self._repository_id, self._release_id, path)
            except Exception as error:  # noqa: BLE001 - the port's failures vary
                warnings.append(f"could not read manifest '{path}': {error}")
                continue

            try:
                documents = list(yaml.safe_load_all(text))
            except yaml.YAMLError as error:
                warnings.append(f"could not parse manifest '{path}': {error}")
                continue

            for document in documents:
                if not isinstance(document, dict):
                    continue
                self._collect(document, path, by_canonical, relationships)

        # Sorted so two derivations over one release produce identical output,
        # which is what lets the fixture diff mean something.
        return tuple(
            relationships[key] for key in sorted(relationships)
        ), tuple(warnings)

    def _collect(self, document, path, by_canonical, relationships) -> None:
        owner = self._owner(document, by_canonical)
        if owner is None:
            return

        for key, value in self._environment(document):
            target = self._target(value, by_canonical)
            if target is None or target.id == owner.id:
                continue

            edge = (owner.id, target.id)
            if edge in relationships:
                continue

            relationships[edge] = ArchitectureRelationship(
                source_id=owner.id,
                target_id=target.id,
                label=self._label(value),
                # Confirmed, because an artifact names both ends explicitly -
                # which is exactly what recovery means by confirmed. Whether
                # the call was *observed* is a different axis entirely, and it
                # travels as `observed: false` below. Conflating the two would
                # cap every manifest-derived relationship at review and leave
                # the pipeline unable to report a violation at all.
                quality=EvidenceQuality.CONFIRMED,
                derived_by=DerivationMethod.DERIVED_FROM_DEPLOYMENT,
                source_paths=(path,),
                attributes={
                    "declared_via": key,
                    "declared_value": value,
                    "observed": False,
                },
            )

    def _owner(self, document: dict, by_canonical) -> ArchitectureElement | None:
        """Which element this manifest describes.

        Taken from the workload's own metadata name. A manifest whose name
        matches no known element is skipped rather than creating one: inventing
        elements here would put things in the graph that recovery never found.
        """

        metadata = document.get("metadata") or {}
        name = metadata.get("name")
        if not isinstance(name, str):
            return None
        return by_canonical.get(canonical_name(name))

    def _environment(self, document: dict):
        """Yield (key, value) for every plain container environment value.

        Values sourced from a secret or config map are skipped: they carry no
        address to match, and treating a reference as a value would produce a
        dependency on the literal string "valueFrom".
        """

        specification = (((document.get("spec") or {}).get("template") or {}).get("spec")) or {}
        for container in specification.get("containers") or []:
            if not isinstance(container, dict):
                continue
            for entry in container.get("env") or []:
                if not isinstance(entry, dict):
                    continue
                key, value = entry.get("name"), entry.get("value")
                if isinstance(key, str) and isinstance(value, str) and _ADDRESS_KEY.search(key):
                    yield key, value

    def _target(self, value: str, by_canonical) -> ArchitectureElement | None:
        match = _ADDRESS_VALUE.match(value.strip())
        if not match:
            return None
        host = match.group("host").split(".")[0]
        return by_canonical.get(canonical_name(host))

    def _label(self, value: str) -> str:
        """Name the transport from the scheme or the port, or say it is unknown.

        A port nobody recognises becomes "declared" rather than a guess. The
        canonical relationship is the same either way; what changes is whether
        the output claims to know something it does not.
        """

        match = _ADDRESS_VALUE.match(value.strip())
        if not match:
            return "declared"
        if match.group("scheme"):
            return match.group("scheme").lower()
        return _PORT_LABELS.get(match.group("port") or "", "declared")
