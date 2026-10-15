"""Recorded snapshot contract, validated at the boundary.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    The schema of the recorded architecture snapshot, and the one place it is
    checked. The architecture document asks that every hand-off use a
    versioned JSON schema and be "validated against that schema before the
    receiving component accepts it" - this is that validation, on the document
    the validation component actually reads.

    Pydantic here and frozen dataclasses inside, each where it belongs. The
    figure tags M1 with Pydantic and the repository's house style keeps
    Pydantic at the edges; both are satisfied by putting the schema in this
    layer and handing the component plain immutable shapes. A declared
    deviation in wording, not in substance.

    ---------------------------------------------------------------------
    STRICT HERE, TOLERANT NEXT DOOR - AND THE REASON IS OWNERSHIP
    ---------------------------------------------------------------------

    `inventory_schema.py` is deliberately forgiving about vocabulary it does
    not recognise: the inventory is **recovery's** document, recovery is still
    being built, and a word we have not learned yet is not a reason to stop.

    This document is **ours**. The recorder writes it and this reader reads it,
    both from the same dataclasses, so an unrecognised element kind or
    evidence quality here is not upstream drift - it is a hand-edited file or
    two halves of this codebase at different versions. Those are worth
    stopping for, and stopping names the field.

    The one exception is `style`, which is tolerant for a reason of its own:
    an unrecognised style is reported as undetermined and normalised
    generically, because the architectural style has a representable "could
    not tell" and an element kind does not.

    What is tolerated either way: **unknown fields.** A document that gains a
    key is read without complaint, because gaining keys is what happens while
    the shape is still settling, and refusing one would make every additive
    change a breaking change.
"""

from pydantic import BaseModel, ConfigDict, ValidationError

SNAPSHOT_SCHEMA_VERSION = "1.0.0"
"""The snapshot schema version this reader targets.

Checked rather than recorded. A version stamped in a document but never
compared is decoration: the point of having one is that a breaking change
announces itself as "this snapshot is schema 2, this reader targets 1" instead
of surfacing as a missing key somewhere else two days later.
"""


class SnapshotContractError(RuntimeError):
    """The recorded snapshot cannot be read as the contract this code targets."""


class SnapshotVersionError(SnapshotContractError):
    """The snapshot's schema version is not the one this reader targets.

    Carries both versions, because the useful question on seeing this is not
    "what broke" but "what changed", and the answer is the pair.
    """

    def __init__(self, found: str, source: str, targets: str = SNAPSHOT_SCHEMA_VERSION) -> None:
        super().__init__(
            f"Recorded snapshot at '{source}' is schema version '{found}', "
            f"this reader targets '{targets}'. Re-record the release."
        )
        self.found = found
        self.targets = targets
        self.source = source


class SnapshotFieldError(SnapshotContractError):
    """A field the reader depends on is absent or unusable.

    `problems` keeps one line per field rather than only the first, because a
    document written by hand is usually wrong in more than one place and
    finding out one field at a time is the slow way to fix it.
    """

    def __init__(self, source: str, problems: tuple[str, ...]) -> None:
        listed = "; ".join(problems)
        super().__init__(f"Recorded snapshot at '{source}' is not valid: {listed}.")
        self.problems = problems
        self.source = source


class _Tolerant(BaseModel):
    """Unknown keys are ignored; declared ones are required unless defaulted."""

    model_config = ConfigDict(extra="ignore")


class ElementDocument(_Tolerant):
    """One element, as the snapshot records it."""

    id: str
    name: str
    kind: str
    quality: str
    source_paths: list[str] = []


class RelationshipDocument(_Tolerant):
    """One relationship, as the snapshot records it."""

    source_id: str
    target_id: str
    label: str
    quality: str
    derived_by: str
    source_paths: list[str] = []
    attributes: dict = {}


class ProvenanceDocument(_Tolerant):
    """Where the recording came from."""

    reader: str = ""
    source_schema_version: str = ""
    source_reference: str = ""


class SnapshotDocument(_Tolerant):
    """One recorded architecture snapshot.

    `style` and `style_source` are optional because a recording made before
    they existed is still readable, and the reader supplies the honest default
    for each: undetermined, and not recovery's answer.
    """

    schema_version: str
    elements: list[ElementDocument]
    relationships: list[RelationshipDocument]
    repository_id: str | None = None
    release_id: str | None = None
    style: str | None = None
    style_source: str | None = None
    manifest_paths: list[str] = []
    provenance: ProvenanceDocument | None = None


def parse_snapshot(document: dict, source: str) -> SnapshotDocument:
    """Validate one snapshot document, or raise naming what is wrong with it.

    The version is checked first and on its own. A schema move usually makes
    several fields look wrong at once, and "six fields are missing" is a much
    worse answer than "this is schema 2 and I read schema 1" when the second
    one is available.
    """

    if not isinstance(document, dict):
        raise SnapshotFieldError(source, ("the document is not a JSON object",))

    found = document.get("schema_version")
    if found is None:
        raise SnapshotFieldError(source, ("'schema_version' is missing",))
    if str(found) != SNAPSHOT_SCHEMA_VERSION:
        raise SnapshotVersionError(str(found), source)

    try:
        return SnapshotDocument.model_validate(document)
    except ValidationError as error:
        raise SnapshotFieldError(source, _describe(error)) from error


def _describe(error: ValidationError) -> tuple[str, ...]:
    """Turn a validation error into one readable line per problem.

    Pydantic's own rendering is several lines per field and names its internal
    types. What a reader needs is the path to the field and what is wrong with
    it, which is the pair below.
    """

    lines = []
    for problem in error.errors():
        location = ".".join(str(part) for part in problem["loc"]) or "the document"
        lines.append(f"'{location}' {problem['msg'].lower()}")
    return tuple(lines)


__all__ = [
    "SNAPSHOT_SCHEMA_VERSION",
    "ElementDocument",
    "ProvenanceDocument",
    "RelationshipDocument",
    "SnapshotContractError",
    "SnapshotDocument",
    "SnapshotFieldError",
    "SnapshotVersionError",
    "parse_snapshot",
]
