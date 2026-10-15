"""Repository inventory translation.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Turns a repository inventory document into the recovered architecture that
    validation consumes.

    This is the only module in the codebase that knows the inventory's field
    names. That is the whole point of it: when recovery renames something, one
    file changes and nothing inside the validation component does.

    Two things the inventory does not currently provide, and how each is
    handled here rather than deeper in.

    It reports no element-to-element relationships. All of its relationship
    types point at a component - a file is in one, a manifest defines one, a
    test targets one - so a release arrives with elements and no edges between
    them. This translation returns them empty and lets validation derive them,
    which keeps the derivation switchable off by the presence of real ones.

    It carries no architectural style yet. The architecture document gives
    recovery the job of detecting it, so this reads an `architecture_style`
    field when one is present and reports its absence otherwise - it does not
    infer. The inference belongs to the normaliser, which has it in one place
    for all three readers; see `observation_normalization/_style.py`.
"""

from app.domain.recovered_architecture import (
    ArchitectureElement,
    ArchitectureStyle,
    ElementKind,
    EvidenceQuality,
    RecoveredArchitecture,
    RecoveryProvenance,
    StyleSource,
)

from .inventory_schema import (
    ARCHITECTURAL_COMPONENT_KINDS,
    COMPONENT_KIND_BUILD_UNIT,
    COMPONENT_KIND_DEPLOYMENT_SERVICE,
    CONFIDENCE_CONFIRMED,
    MANIFEST_CATEGORIES,
    assert_shape,
    assert_version,
    require,
)

_KIND_MAP = {
    COMPONENT_KIND_DEPLOYMENT_SERVICE: ElementKind.SERVICE,
    COMPONENT_KIND_BUILD_UNIT: ElementKind.MODULE,
}

# A build unit that a deployment manifest names is a deployed service. The
# inventory classifies components by how it found them - a go.mod makes a
# build unit - so a repository whose services are all discovered that way
# reports no deployment services at all, even when every one of them has a
# manifest. Reading the manifest filenames recovers what the kind alone loses.
_DEPLOYED_PROMOTION = ElementKind.SERVICE

STYLE_FIELD = "architecture_style"
"""The field recovery supplies the detected style in.

Named here because this is the only module allowed to know the inventory's
field names. It is absent from every inventory recovery writes today; §4.4 of
the architecture document lists it as part of the hand-off, and it is one of
the two fields outstanding on that contract.
"""


def translate(
    document: dict,
    repository_id: str,
    release_id: str,
    source_reference: str,
    reader: str,
) -> RecoveredArchitecture:
    """Translate one inventory document for one release.

    `release_id` comes from the caller rather than the document: the inventory
    identifies a release by commit, and commit hashes carry no order, which
    the validity intervals in the knowledge model require.
    """

    assert_version(document)
    assert_shape(document)

    elements = _elements(document)
    style, style_source = read_style(document)

    return RecoveredArchitecture(
        repository_id=repository_id,
        release_id=release_id,
        style=style,
        style_source=style_source,
        elements=elements,
        # Empty by design - see the module docstring. Validation derives these
        # and stops as soon as the inventory reports real ones.
        relationships=(),
        manifest_paths=manifest_paths(document),
        provenance=RecoveryProvenance(
            reader=reader,
            source_schema_version=document["schema_version"],
            source_reference=source_reference,
        ),
    )


def _elements(document: dict) -> tuple[ArchitectureElement, ...]:
    """Map inventory components to architectural elements.

    Components the inventory only inferred from directory structure are not
    elements; see ARCHITECTURAL_COMPONENT_KINDS for why.
    """

    paths_by_component = _paths_by_component(document)
    deployed = _deployed_names(document)
    elements = []

    for component in document["components"]:
        where = "components[]"
        kind = require(component, "kind", where)
        if kind not in ARCHITECTURAL_COMPONENT_KINDS:
            continue

        component_id = require(component, "id", where)
        name = require(component, "name", where)
        elements.append(
            ArchitectureElement(
                id=component_id,
                name=name,
                kind=(
                    _DEPLOYED_PROMOTION
                    if canonical(name) in deployed
                    else _KIND_MAP[kind]
                ),
                quality=(
                    EvidenceQuality.CONFIRMED
                    if require(component, "confidence", where) == CONFIDENCE_CONFIRMED
                    else EvidenceQuality.INFERRED
                ),
                source_paths=paths_by_component.get(component_id, ()),
            )
        )

    # Sorted so two translations of one inventory produce identical output.
    # Fact ids are content-addressed and would survive reordering, but a
    # fixture diff would not, and the fixture is how a recovery change is
    # noticed.
    return tuple(sorted(elements, key=lambda element: element.id))


def _deployed_names(document: dict) -> frozenset[str]:
    """Canonical names that appear as a manifest filename.

    `kustomize/base/adservice.yaml` says adservice is deployed. Matching on the
    filename rather than parsing the manifest keeps this translation free of
    Kubernetes semantics, which belong in the derivation.
    """

    names = set()
    for record in document.get("files", []):
        if record.get("category") not in MANIFEST_CATEGORIES:
            continue
        path = record.get("path", "")
        stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if stem and stem != "kustomization":
            names.add(canonical(stem))
    return frozenset(names)


def _paths_by_component(document: dict) -> dict[str, tuple[str, ...]]:
    """Group the files the inventory attributed to each component.

    Only manifest-ish categories are kept. Every source file of every service
    would make the elements enormous and none of it is evidence validation
    reasons from.
    """

    grouped: dict[str, list[str]] = {}
    for record in document.get("files", []):
        component_id = record.get("component_id")
        if not component_id or record.get("category") not in MANIFEST_CATEGORIES:
            continue
        grouped.setdefault(component_id, []).append(record.get("path", ""))
    return {key: tuple(sorted(paths)) for key, paths in grouped.items()}


def manifest_paths(document: dict) -> tuple[str, ...]:
    """Every deployment or infrastructure manifest the inventory found.

    Exposed because the relationship derivation needs these paths and should
    not have to re-learn the inventory's file vocabulary to get them.
    """

    paths = [
        record["path"]
        for record in document.get("files", [])
        if record.get("category") in MANIFEST_CATEGORIES and record.get("path")
    ]
    return tuple(sorted(paths))


def canonical(name: str) -> str:
    """Lowercase and strip separators, for comparing a filename to a name."""

    return name.strip().lower().replace("-", "").replace("_", "").replace(".", "")


def read_style(document: dict) -> tuple[ArchitectureStyle, StyleSource]:
    """Return recovery's detected style and the fact that it was recovery's.

    Three cases, and none of them raises. Absent is the normal case today and
    hands the question to the normaliser, labelled. A value recovery wrote is
    authoritative even when it is `unknown`: recovery looked and could not
    tell, which is an answer and not a gap.

    A value this version does not recognise is also recovery's answer, and is
    reported as `unknown` from recovery rather than refused. Recovery adding a
    style before validation learns the word is ordinary drift between two
    components being built in parallel, and the right response is the generic
    adapter with its confidence capped - not a run that stops. Failing loud on
    contract drift is M8's job in the component diagram, not this layer's.
    """

    if STYLE_FIELD not in document or document[STYLE_FIELD] in (None, ""):
        return ArchitectureStyle.UNKNOWN, StyleSource.INFERRED_BY_C2

    try:
        return ArchitectureStyle(document[STYLE_FIELD]), StyleSource.C1
    except ValueError:
        return ArchitectureStyle.UNKNOWN, StyleSource.C1
