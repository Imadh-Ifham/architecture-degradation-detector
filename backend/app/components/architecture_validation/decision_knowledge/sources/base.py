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
    Span,
)

FRONT_MATTER_FENCE = "---"

ADR_DIRECTORY_PATTERNS = (
    "**/adr/**/*.md",
    "**/ADR/**/*.md",
    "**/decisions/**/*.md",
)
"""Directories a team dedicates to decision records, at any depth.

**Recursive at both ends, and the prefix is the half that was missing.** A
directory named `adr` anywhere in the tree is a deliberate statement; one named
`docs/adr` at the root is the same statement made at the root. Anchoring the
patterns there found a monorepository's shared records and missed every
per-service set - 37 of 138 on the first repository that keeps them that way,
because each bounded context carries its own `docs/ADR/decisions/`.

Three patterns rather than the seven this list used to hold, because `**/adr/**`
already covers `doc/adr`, `docs/adr` and a bare `adr`. Fewer patterns that each
say one thing beat a list that enumerates layouts, which is a list that is
always one layout out of date.

Case is spelled out rather than folded. `Path.glob` is case-insensitive on
Windows and case-sensitive elsewhere, so a pattern that works on the author's
machine and not on a marker's is the failure this avoids - and the matches are
deduplicated case-insensitively further down for the same reason.

**Not `**/*.md`.** That is 490 files on this repository, and a source that reads
every markdown file in a monorepository will parse a changelog as a decision.

A document found under one of these is an *attempted* decision record even when
it cannot be parsed, which is what makes the count worth reporting separately.
"""

OTHER_DOCUMENT_PATTERNS = (
    "docs/*.md",
    "architecture/*.md",
    "*.md",
)
"""Places a decision record sometimes sits among ordinary prose.

One level only, and deliberately. A source that reads every markdown file in a
repository will eventually parse a changelog as a decision, and a monorepository
has hundreds. A document found here is not evidence that the team keeps records.
"""

DECISION_DOCUMENT_PATTERNS = ADR_DIRECTORY_PATTERNS + OTHER_DOCUMENT_PATTERNS


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
    source_span: Span | None = None,
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
        source_span=source_span,
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
) -> tuple[tuple[DecisionRecord, ...], int]:
    """Read the decision records written in one repository.

    Shared by both declared sources, because the only thing that differs
    between records kept beside the code and records kept in their own
    repository is which repository they are read from.

    A markdown file with no front matter is not a decision record and is
    passed over in silence - most markdown in a repository is prose. Front
    matter that names a constraint *is* an attempted record, so a missing
    field there is an error rather than a reason to skip: a record whose
    validity interval had to be guessed is worse than no record at all.

    Returns the records and **how many documents sat in a directory the team
    dedicates to decisions.** Those two numbers answer different questions, and
    a caller that only had the first would report "this repository keeps no
    decision records" about a repository keeping forty-one of them in prose.
    `0 of 0` is a finding about the team; `0 of 41` is a finding about the
    format, and conflating them misstates the result the whole design rests on.
    """

    records: list[DecisionRecord] = []
    seen: set[str] = set()
    in_adr_directory = 0

    for pattern in DECISION_DOCUMENT_PATTERNS:
        for path in reader.list_paths(repository_id, request.release_id, pattern):
            # Case-folded, because `Path.glob` is case-insensitive on Windows:
            # `docs/adr/**` and `docs/ADR/**` there return the same files under
            # the pattern's own casing, so matching on the path as given counts
            # every record twice on one platform and once on another. A number
            # that depends on the developer's operating system is worse than a
            # wrong one, because it looks right wherever it is checked.
            key = path.casefold()
            if key in seen:
                continue
            seen.add(key)

            if pattern in ADR_DIRECTORY_PATTERNS:
                in_adr_directory += 1

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

    return tuple(records), in_adr_directory


def declared_source_reason(
    records: tuple[DecisionRecord, ...], in_adr_directory: int, where: str
) -> str | None:
    """Why a declared source produced nothing, told apart from having nothing to find.

    `0 of 0` is a finding about the team: they keep no decision records. `0 of
    41` is a finding about the *format* - they keep forty-one, in prose, and
    this reader turns none of them into a constraint. The second is the
    stronger result and the harder one to report, because the obvious
    implementation reports both as a zero and the research claim rests on the
    difference.
    """

    if records:
        return None
    if in_adr_directory:
        return (
            f"{in_adr_directory} decision document(s) found in {where}; none "
            "declares a machine-readable constraint"
        )
    return f"no decision records in {where}"


def _optional(value) -> str | None:
    return str(value) if value else None


__all__ = [
    "ADR_DIRECTORY_PATTERNS",
    "DECISION_DOCUMENT_PATTERNS",
    "OTHER_DOCUMENT_PATTERNS",
    "REQUIRED_FIELDS",
    "DecisionSource",
    "DecisionSourceError",
    "SourceOutcome",
    "SourceRequest",
    "collect_decision_documents",
    "declared_source_reason",
    "decision_record",
    "parse_front_matter",
]
