"""What a decision source is, and the one place a record gets built.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    A decision source is somewhere architectural decisions can be found. There
    are three: records written in the code repository, records written in a
    repository the user names, and rules reconstructed from the code
    repository's own configuration.

    All three answer the same question - what governs this release - and all
    three answer it in the same shape: the records, plus why there were none.
    A source that was never configured and a source that ran and found nothing
    are different answers, and the difference decides whether a run is refused
    or reported.

    `decision_record()` is the only place in this subcomponent that builds a
    DecisionRecord. Normalisation learned that the expensive way: adding one
    field to the fact meant seven edits across five adapters, and the site
    that was missed would not have failed anything.

    Nothing here opens a file. Sources are handed a reader and ask it for
    text, which is what keeps this component out of the repository it is
    reasoning about.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import yaml

from ...models import (
    ConstraintKind,
    DecisionRecord,
    EvidenceStrength,
    ExtractionMethod,
    SourceTier,
)

FRONT_MATTER_FENCE = "---"

DECISION_DOCUMENT_PATTERNS = (
    "doc/adr/*.md",
    "docs/adr/*.md",
    "docs/decisions/*.md",
    "docs/*.md",
    "adr/*.md",
    "architecture/*.md",
    "*.md",
)
"""Where decision records are kept, in rough order of how conventional it is.

A list rather than a recursive walk: a source that reads every markdown file
in a repository will eventually parse a changelog as a decision. Each pattern
here is a place a team deliberately puts decisions.
"""


class DecisionSourceError(ValueError):
    """A source found something it cannot read.

    Raised rather than skipped. Absence closes a validity interval, so a
    document this cannot parse would otherwise read as a rule being withdrawn
    between one release and the next.
    """


@dataclass(frozen=True)
class SourceRequest:
    """What every source is asked.

    One shape for three sources, each taking the fields it needs. The code
    repository and the decision repository are named separately because modes
    2 and 3 read two different repositories, and a single `repository_id`
    would leave each source guessing which one it meant.

    `manifest_paths` comes from the recovered architecture. Recovery already
    located and classified every deployment manifest, so the configuration
    scan is handed the list rather than searching for it - which is what keeps
    one opinion about the repository's layout rather than two.

    `extracted_at` is supplied rather than read from the clock. Two scans of
    one release have to produce the same records, and a timestamp taken inside
    the scan would make every re-run differ from the last.
    """

    code_repository_id: str
    release_id: str
    extracted_at: datetime
    manifest_paths: tuple[str, ...] = ()
    adr_repository_id: str | None = None


@dataclass(frozen=True)
class SourceOutcome:
    """What one source found for one release.

    `ran` is the distinction the gate is built on. A source that could not run
    - no decision repository was named - has not told us anything about the
    system. A source that ran and returned nothing has: it says this
    repository keeps no decision records, which is a finding.
    """

    source: str
    ran: bool
    records: tuple[DecisionRecord, ...] = ()
    reason: str | None = None


class DecisionSource(Protocol):
    """One place decisions can be found.

    A single method, on purpose. The obvious alternative - a cheap `count()`
    for the mode picker and a real `collect()` for the run - is two
    implementations of one question, and the day they disagree the picker
    promises records the run does not produce. Collecting is deterministic,
    reads a handful of files and calls no model, so the picker simply collects.
    """

    name: str

    def collect(self, request: SourceRequest) -> SourceOutcome:
        """Return everything this source holds for the requested release."""
        ...


def decision_record(
    request: SourceRequest,
    *,
    decision_id: str,
    subject: str,
    constraint: ConstraintKind,
    object_: str,
    source: str,
    source_repository: str,
    source_ref: str,
    source_tier: SourceTier,
    source_strength: EvidenceStrength,
    extraction_method: ExtractionMethod,
    rationale: str | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
    supersedes: str | None = None,
) -> DecisionRecord:
    """Build one decision record, with its provenance filled from `request`.

    `valid_from` defaults to the release being scanned, which is the honest
    answer: this is the earliest release the rule is known to have been in
    force for. Whether it was in force earlier is a question about releases
    nobody has scanned yet, and the knowledge log answers it by accumulating
    rather than by guessing here.

    Subject and object are kept as the document wrote them. Matching them
    against an element reduces both sides to a canonical form, and that
    reduction belongs to the lookup rather than to the record - a record that
    only holds `cart` can no longer be shown to an architect as the rule about
    `cart-service` that it is.
    """

    return DecisionRecord(
        decision_id=decision_id,
        subject=subject,
        constraint=constraint,
        object=object_,
        valid_from=valid_from or request.release_id,
        valid_to=valid_to,
        source=source,
        source_repository=source_repository,
        source_tier=source_tier,
        source_strength=source_strength,
        source_ref=source_ref,
        extraction_method=extraction_method,
        extracted_at=request.extracted_at,
        rationale=rationale,
        supersedes=supersedes,
    )


def parse_front_matter(text: str) -> dict | None:
    """Return the YAML front matter of a markdown document, or None.

    None means the document has no front matter at all, which is the normal
    state of almost every markdown file in a repository. Telling that apart
    from a malformed decision record is the whole reason this returns rather
    than raises.
    """

    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONT_MATTER_FENCE:
        return None

    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == FRONT_MATTER_FENCE:
            block = yaml.safe_load("\n".join(lines[1:index]))
            return block if isinstance(block, dict) else None
    return None


REQUIRED_FIELDS = ("id", "subject", "constraint", "object", "valid_from")


def collect_decision_documents(
    reader, repository_id: str, request: SourceRequest, source: str
) -> tuple[DecisionRecord, ...]:
    """Read the decision records written in one repository.

    Shared by both declared sources, because the only thing that differs
    between records kept beside the code and records kept in their own
    repository is which repository they are read from.

    A markdown file with no front matter is not a decision record and is
    passed over in silence - most markdown in a repository is prose. Front
    matter that names a constraint *is* an attempted record, so a missing
    field there is an error rather than a reason to skip: a record whose
    validity interval had to be guessed is worse than no record at all.
    """

    records: list[DecisionRecord] = []
    seen: set[str] = set()

    for pattern in DECISION_DOCUMENT_PATTERNS:
        for path in reader.list_paths(repository_id, request.release_id, pattern):
            if path in seen:
                continue
            seen.add(path)

            front_matter = parse_front_matter(
                reader.read_text(repository_id, request.release_id, path)
            )
            if not front_matter or "constraint" not in front_matter:
                continue

            missing = [field for field in REQUIRED_FIELDS if not front_matter.get(field)]
            if missing:
                raise DecisionSourceError(
                    f"'{path}' declares a constraint but is missing "
                    f"{', '.join(missing)}."
                )

            constraint = str(front_matter["constraint"])
            if constraint not in set(ConstraintKind):
                raise DecisionSourceError(
                    f"'{path}' uses the constraint '{constraint}', which is not "
                    f"one of {', '.join(sorted(ConstraintKind))}."
                )

            records.append(
                decision_record(
                    request,
                    decision_id=str(front_matter["id"]),
                    subject=str(front_matter["subject"]),
                    constraint=ConstraintKind(constraint),
                    object_=str(front_matter["object"]),
                    source=source,
                    source_repository=repository_id,
                    source_ref=path,
                    source_tier=SourceTier.DECISION_RECORD,
                    source_strength=EvidenceStrength.AUTHORITATIVE,
                    extraction_method=ExtractionMethod.DECLARED,
                    rationale=front_matter.get("rationale"),
                    valid_from=str(front_matter["valid_from"]),
                    valid_to=_optional(front_matter.get("valid_to")),
                    supersedes=_optional(front_matter.get("supersedes")),
                )
            )

    return tuple(records)


def _optional(value) -> str | None:
    return str(value) if value else None


__all__ = [
    "DECISION_DOCUMENT_PATTERNS",
    "REQUIRED_FIELDS",
    "DecisionSource",
    "DecisionSourceError",
    "SourceOutcome",
    "SourceRequest",
    "collect_decision_documents",
    "decision_record",
    "parse_front_matter",
]
