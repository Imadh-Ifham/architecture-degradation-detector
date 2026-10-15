"""Recorded architecture snapshot reader.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    Reads a recorded recovery output - one snapshot document per release - and
    returns it as the validation component's own domain shape.

    This is the reader the component develops and demonstrates against, and it
    is the fallback the methodology describes: where live recovery output is
    not available for a repository, a recorded recovery output is used, so that
    validation can be evaluated independently of recovery's completion
    schedule.

    It differs from the inventory reader in what it reads, not in what it
    returns. The inventory reader translates recovery's raw inventory document
    and is the evidence that the translation is right. This one reads a
    document already in the translated shape, which is what the recorder
    writes. Both satisfy the same port, so which one is wired in is
    configuration and nothing inside the component can tell them apart.

    Every field is validated by `snapshot_schema.py` before anything here
    touches it, so this module contains no field checks of its own - it maps a
    validated document onto the domain vocabulary and nothing else. The one
    judgement left is what to do with a word the vocabulary does not hold, and
    there are exactly two answers: an unrecognised **style** becomes
    undetermined, because "could not tell" is a representable answer for a
    style; anything else raises naming the value, because this document is
    ours and an unrecognised kind means a hand edit or two halves of this
    codebase at different versions.
"""

import json
from pathlib import Path

from app.domain.recovered_architecture import (
    ArchitectureElement,
    ArchitectureRelationship,
    ArchitectureStyle,
    DerivationMethod,
    ElementKind,
    EvidenceQuality,
    RecoveredArchitecture,
    RecoveryProvenance,
    StyleSource,
)

from .snapshot_schema import (
    SNAPSHOT_SCHEMA_VERSION,
    ElementDocument,
    RelationshipDocument,
    SnapshotDocument,
    SnapshotFieldError,
    parse_snapshot,
)

READER_NAME = "snapshot_file_reader"


class SnapshotFileReader:
    """Reads a recovered architecture from a recorded snapshot document."""

    def __init__(self, snapshot_root: Path) -> None:
        self._root = Path(snapshot_root)

    def read(self, repository_id: str, release_id: str) -> RecoveredArchitecture:
        """Return the recorded architecture for one release."""

        path = self._path_for(release_id)
        document = parse_snapshot(self._load(path), str(path))

        return RecoveredArchitecture(
            repository_id=document.repository_id or repository_id,
            release_id=release_id,
            style=self._style(document),
            style_source=self._style_source(document, str(path)),
            elements=tuple(self._element(item, str(path)) for item in document.elements),
            relationships=tuple(
                self._relationship(item, str(path)) for item in document.relationships
            ),
            provenance=RecoveryProvenance(
                reader=READER_NAME,
                source_schema_version=document.schema_version,
                source_reference=str(path),
            ),
            manifest_paths=tuple(document.manifest_paths),
        )

    def manifest_paths(self, release_id: str) -> tuple[str, ...]:
        path = self._path_for(release_id)
        return tuple(parse_snapshot(self._load(path), str(path)).manifest_paths)

    def _path_for(self, release_id: str) -> Path:
        return self._root / f"snapshot_{release_id}.json"

    def _load(self, path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            # Raised rather than returned as an empty architecture: a missing
            # snapshot means nobody recorded this release, which is a different
            # situation from a release that genuinely has no elements.
            raise SnapshotFieldError(
                str(path), ("there is no recording here; record this release first",)
            ) from error
        except json.JSONDecodeError as error:
            raise SnapshotFieldError(str(path), (f"it is not valid JSON: {error}",)) from error

    def _style(self, document: SnapshotDocument) -> ArchitectureStyle:
        """Recovery's style, or undetermined.

        The one tolerant mapping in this reader. A style has a representable
        "could not tell", so an unrecognised word becomes that and the release
        normalises generically with its confidence capped - which is a correct
        answer about an architecture whose style is undetermined.
        """

        try:
            return ArchitectureStyle(document.style)
        except ValueError:
            return ArchitectureStyle.UNKNOWN

    def _style_source(self, document: SnapshotDocument, source: str) -> StyleSource:
        """Who decided the style recorded here.

        Absent defaults to `inferred_by_c2`, never to `c1`. A recording made
        before this field existed cannot show that recovery detected anything,
        and defaulting the other way would turn every old snapshot into a
        claim about recovery's output that nobody made.
        """

        if document.style_source is None:
            return StyleSource.INFERRED_BY_C2
        return self._term(StyleSource, document.style_source, "style_source", source)

    def _element(self, item: ElementDocument, source: str) -> ArchitectureElement:
        return ArchitectureElement(
            id=item.id,
            name=item.name,
            kind=self._term(ElementKind, item.kind, f"element '{item.id}' kind", source),
            quality=self._term(
                EvidenceQuality, item.quality, f"element '{item.id}' quality", source
            ),
            source_paths=tuple(item.source_paths),
        )

    def _relationship(self, item: RelationshipDocument, source: str) -> ArchitectureRelationship:
        where = f"relationship '{item.source_id}' -> '{item.target_id}'"
        return ArchitectureRelationship(
            source_id=item.source_id,
            target_id=item.target_id,
            label=item.label,
            quality=self._term(EvidenceQuality, item.quality, f"{where} quality", source),
            derived_by=self._term(
                DerivationMethod, item.derived_by, f"{where} derived_by", source
            ),
            source_paths=tuple(item.source_paths),
            attributes=dict(item.attributes),
        )

    def _term(self, vocabulary, value: str, where: str, source: str):
        """Map one recorded word onto the domain vocabulary, or raise.

        Raising names the value **and** what the vocabulary holds, because the
        only two reasons to see this are a hand-edited file and a codebase at
        two versions, and both are answered by the list.
        """

        try:
            return vocabulary(value)
        except ValueError as error:
            accepted = ", ".join(sorted(member.value for member in vocabulary))
            raise SnapshotFieldError(
                source,
                (f"{where} is '{value}', which is not one of: {accepted}",),
            ) from error


__all__ = ["READER_NAME", "SNAPSHOT_SCHEMA_VERSION", "SnapshotFileReader"]
