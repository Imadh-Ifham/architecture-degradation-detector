"""Repository inventory contract, as validation reads it.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    The parts of the repository inventory document that validation depends on,
    and the version of that document this translation targets.

    Tolerant on what it does not use, strict on what it does. An inventory that
    gains a field is read without complaint, because gaining fields is what
    actually happens while recovery is being built out. An inventory missing a
    field validation needs fails immediately, naming the field.

    `CONTRACT_VERSION` is checked rather than recorded. A version stamped in
    the output but never compared is decoration: the point of having one is
    that a breaking change announces itself as "inventory is schema 2, this
    translation targets 1" instead of surfacing as a KeyError two days later in
    unrelated code.

    **One of recovery's three component kinds is dropped, on purpose.**
    `deployment_service` and `build_unit` become architectural elements;
    `directory_group` does not. It means "these files sit in a folder
    together", which is a filesystem fact rather than an architectural one -
    promoting it would put directories in the validated graph, and every
    verdict about a directory would be noise. It would also inflate the one
    number that is easiest to misread: a directory can never be governed by an
    architectural decision, so counting it as an element would count it as
    ungoverned.

    Written here as well as beside `ARCHITECTURAL_COMPONENT_KINDS` so that a
    later reader finding a kind being dropped does not "fix" it. The cost is
    real and belongs in threats to validity: a repository whose only visible
    structure is its folder layout yields very few elements, and on such a
    repository this component has almost nothing to validate. That is a limit
    of the input, not of the rule.

    Tolerant on vocabulary, by contrast with `snapshot_schema.py`, which is
    strict. This document is recovery's and recovery is still being built; the
    snapshot is ours, written and read from the same dataclasses, so an
    unrecognised word there means something quite different.
"""

CONTRACT_VERSION = "1.0.0"
"""The inventory schema version this translation was written against."""

REQUIRED_TOP_LEVEL = ("schema_version", "repository", "components", "relationships")
"""Keys validation cannot proceed without.

`files` and `classifications` are not here. Validation needs them only to find
deployment manifests, and an inventory that recorded no files is a repository
with nothing to validate rather than a malformed document.
"""


class InventoryContractError(RuntimeError):
    """The inventory cannot be read as the contract this code targets."""


class InventoryVersionError(InventoryContractError):
    """The inventory's schema version is not the one this translation targets.

    Carries both versions, because the useful question on seeing this is not
    "what broke" but "what changed", and the answer is the pair.
    """

    def __init__(self, found: str, targets: str = CONTRACT_VERSION) -> None:
        super().__init__(
            f"Repository inventory is schema {found}, this translation targets {targets}. "
            "Re-run the inventory, or update app/infrastructure/recovery_gateway/."
        )
        self.found = found
        self.targets = targets


class InventoryFieldError(InventoryContractError):
    """A field validation depends on is absent."""

    def __init__(self, field: str, where: str) -> None:
        super().__init__(f"Repository inventory is missing '{field}' in {where}.")
        self.field = field
        self.where = where


# Vocabulary the inventory uses. Mirrored rather than imported: importing
# recovery's enums would couple the two components' code, and this is the one
# file whose job is to know recovery's names. If a value is added upstream,
# this is the only place that needs to learn it.
#
# Note on shape: in the serialised document a relationship's ends are nested -
# {"source": {"kind", "id"}, "target": {"kind", "id"}} - even though the
# dataclass that produces it has flat source_kind/source_id fields. Read the
# JSON, not the dataclass. Validation does not consume these relationships
# today, but anything that starts to must use the nested form.
COMPONENT_KIND_BUILD_UNIT = "build_unit"
COMPONENT_KIND_DEPLOYMENT_SERVICE = "deployment_service"
COMPONENT_KIND_DIRECTORY_GROUP = "directory_group"

CONFIDENCE_CONFIRMED = "confirmed"
CONFIDENCE_INFERRED = "inferred"

CATEGORY_DEPLOYMENT_MANIFEST = "deployment_manifest"
CATEGORY_INFRASTRUCTURE_CONFIG = "infrastructure_config"
CATEGORY_API_SPECIFICATION = "api_specification"

ARCHITECTURAL_COMPONENT_KINDS = frozenset(
    {COMPONENT_KIND_DEPLOYMENT_SERVICE, COMPONENT_KIND_BUILD_UNIT}
)
"""Which inventory components count as architectural elements.

`directory_group` is excluded deliberately. It means "these files sit in a
folder together", which is a filesystem fact rather than an architectural one.
Promoting it would put directories in the validated graph, and every verdict
about one would be noise.
"""

MANIFEST_CATEGORIES = frozenset(
    {CATEGORY_DEPLOYMENT_MANIFEST, CATEGORY_INFRASTRUCTURE_CONFIG}
)
"""File categories searched when deriving relationships.

Both are included because the classifier's boundary between them is not
something validation should depend on: a Kubernetes manifest under a kustomize
component directory could reasonably land in either.
"""


def assert_version(document: dict) -> None:
    """Raise unless the document is the schema version this code targets."""

    found = document.get("schema_version")
    if found is None:
        raise InventoryFieldError("schema_version", "the inventory document")
    if found != CONTRACT_VERSION:
        raise InventoryVersionError(found)


def assert_shape(document: dict) -> None:
    """Raise unless every key validation depends on is present."""

    for key in REQUIRED_TOP_LEVEL:
        if key not in document:
            raise InventoryFieldError(key, "the inventory document")


def require(mapping: dict, field: str, where: str):
    """Return `mapping[field]`, or raise naming the field and its context."""

    if field not in mapping:
        raise InventoryFieldError(field, where)
    return mapping[field]
