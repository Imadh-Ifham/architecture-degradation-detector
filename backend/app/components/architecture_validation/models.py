"""Architecture validation data model.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    The shapes that pass between this component's subcomponents. Anything used
    by only one subcomponent belongs in that subcomponent's own models.py; the
    two shapes that cross a component boundary live in `app/domain/`.

    One rule runs through the whole file and is worth stating once: the
    strength of the evidence puts a ceiling on the strength of the conclusion.
    A relationship inferred from directory structure, or an intent read out of
    a commit message, can be raised for review but can never be reported as a
    violation. The ceiling is enforced in code rather than asked for in a
    prompt, so it holds even when a model is wrong.

    `DecisionRecord` deliberately gives its provenance fields no defaults. A
    record whose origin is unknown is then impossible to construct, rather than
    possible to construct and easy to forget about.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class RelationshipKind(StrEnum):
    """Validation's canonical relationship vocabulary.

    Closed and small by design. Every architectural style reduces into these
    two, with everything style-specific kept in the fact's attributes - which
    is what lets one validation algorithm serve every style instead of
    branching per style.
    """

    COMMUNICATES_WITH = "communicates-with"
    DEPENDS_ON = "depends-on"


class SourceTier(StrEnum):
    """Where a statement of intent was found.

    Ordered strongest to weakest. The tiers exist because most repositories
    hold no decision records at all, so intent has to be read from whatever
    the repository does contain - and what it was read from has to travel with
    it, or a weak source silently produces a confident accusation.

    Tier 2 sits as high as Tier 1 for structural rules on purpose: a network
    policy or a service contract is unambiguous, versioned, current and
    actually enforced, and a prose decision record is none of those four.
    Decision records remain the better source for *why* a rule exists.
    """

    DECISION_RECORD = "tier_1_decision_record"
    EXECUTABLE_CONFIG = "tier_2_executable_config"
    DOCUMENTATION = "tier_3_documentation"
    HISTORY = "tier_4_history"
    CONVENTION = "tier_5_convention"


class EvidenceStrength(StrEnum):
    """How far a source is allowed to carry a conclusion."""

    AUTHORITATIVE = "authoritative"
    SUPPORTING = "supporting"
    WEAK = "weak"


class ExtractionMethod(StrEnum):
    """How a decision record came to exist.

    `RECONSTRUCTED` records keep this value for life, including after an
    architect ratifies them. Clearing it would turn the pipeline into a way of
    manufacturing its own ground truth, and six months later nobody could tell
    which decisions a person originally wrote.
    """

    DECLARED = "declared"
    RECONSTRUCTED = "reconstructed"


class ConstraintKind(StrEnum):
    """What a decision actually requires of the architecture."""

    MUST_NOT_CALL = "must_not_call"
    MAY_CALL = "may_call"
    MUST_CALL_VIA = "must_call_via"
    DECLARED_RPC = "declared_rpc"


WILDCARD = "*"
"""What a decision writes when it is about every element rather than a pair.

A default-deny policy is one record about every pair, so it is `*` on both
sides rather than one refusal per unpermitted pair - 116 records on a
twelve-element system, all saying the same thing.

It sits here rather than in the subcomponent that first needed it because two
of them now read it: the resolver falls back to the general refusal when no
rule names a pair, and the arbiter has to tell that refusal apart from a named
prohibition. Two spellings of "about everything" would be two answers to
whether a fact was specifically forbidden.
"""


class Verdict(StrEnum):
    """What the reasoner concluded about one fact against one decision.

    `INSUFFICIENT_EVIDENCE` is what a failed or unusable model response
    becomes. It is never replaced by a guess: a system that answers when it is
    confused produces output indistinguishable from output it is sure about.
    """

    CONFIRMS = "confirms"
    CONTRADICTS = "contradicts"
    PARTIALLY_CONFIRMS = "partially_confirms"
    UNRELATED = "unrelated"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class VerificationOutcome(StrEnum):
    """Whether the verifier accepted the reasoner's verdict.

    Can only lower an outcome, never raise one. The verifier saw the same
    evidence, so its agreement says something about the models rather than
    about the architecture.
    """

    AGREE = "agree"
    DISAGREE = "disagree"
    UNCERTAIN = "uncertain"


class VerificationMode(StrEnum):
    """Whether a run verified its verdicts, and if not, why not.

    Three values because they are the three honest things a run can say, and
    the last two are the ones that must not collapse into each other.
    `NOT_REQUESTED` is the architect's own decision and reflects on nothing;
    `UNAVAILABLE` is a fault in the environment and may be the most important
    line in the result. One `skipped` covering both would lose the only half
    that is actionable.

    It sits on the run rather than on each fact because it describes the whole
    of it: one answer decided whether a second model was asked about any of
    these verdicts, and the summary a person reads above the counts is a
    statement about the run.

    Distinct from `VerificationOutcome`, which is what the verifier *said*.
    This is whether it was asked.
    """

    PERFORMED = "performed"
    NOT_REQUESTED = "not_requested"
    UNAVAILABLE = "unavailable"


class VerificationArm(StrEnum):
    """What the verifier was allowed to see.

    A second axis from `VerificationMode`, not a widening of it: that field
    says whether verification ran, this one says what it was shown.
    Collapsing them would make *nobody asked for it* and *it ran blind* the
    same string.

    `INFORMED` is the default and the demonstration mode - the verifier is
    shown the verdict and asked what is wrong with the argument, which is the
    only output here an architect can act on. `BLIND` shows it the evidence
    and not the answer, which buys an unanchored opinion and no objections.
    `BOTH` is three model calls a fact and is a measurement mode: the
    difference between the two agreement rates is the anchoring effect,
    measured rather than conceded.
    """

    INFORMED = "informed"
    BLIND = "blind"
    BOTH = "both"


class VerdictSource(StrEnum):
    """What produced a verdict.

    `ARBITER` means no model was involved at all: every rung above the last
    one failed, and the deterministic table was the whole of it. Published on
    the verdict, and from there onto the published edge, because a run with a
    dead key would otherwise be indistinguishable from a successful one.
    """

    MODEL = "model"
    ARBITER = "arbiter"


class ArbiterAgreement(StrEnum):
    """What comparing the model's verdict with the table's concluded.

    The two kinds of silence are different and keeping them apart is the
    point. `NOT_COMPARABLE` means the model answered in a vocabulary the table
    does not share - `partially_confirms` and `unrelated` are refinements a
    two-value oracle cannot speak to, and calling that a disagreement would
    manufacture a conflict out of a vocabulary mismatch. `NOT_CHECKED` means
    the table abstained, so nothing checked this fact.

    The field that carries this is nullable, and null is a third absence
    again: on a verdict the arbiter itself produced there is no model verdict
    to compare with, and `NOT_CHECKED` would be wrong because the table did
    not abstain - it answered.
    """

    AGREED = "agreed"
    DISAGREED = "disagreed"
    NOT_COMPARABLE = "not_comparable"
    NOT_CHECKED = "not_checked"


class GuardFailure(StrEnum):
    """Why a model response was rejected.

    Recorded rather than collapsed into a single error, because the failures
    mean different things: a malformed response is a schema or provider
    problem, and a citation that resolves to nothing is the model inventing
    evidence.

    It sits at the component level rather than inside the reasoner because the
    verdict publishes it and because verification reuses the same guards. Two
    vocabularies for one rejection would be two answers to why a fact was
    held back.
    """

    MALFORMED = "malformed"
    UNRESOLVED_CITATION = "unresolved_citation"
    NO_CITATION = "no_citation"
    CONTEXT_ONLY_CITATION = "context_only_citation"
    SUPERSEDED_AS_GOVERNING = "superseded_as_governing"
    INCOHERENT_OUTCOME = "incoherent_outcome"
    """The verifier's conclusion and its own objections disagree.

    Three faults listed and then `agree`, or `disagree` with nothing to point
    at. The response is schema-valid, every reference in it resolves, and it
    contradicts itself - which is common on a small model asked for a list
    and a judgement in one answer, and is why the rate of it is worth
    publishing rather than logging.
    """
    """The two that are about a citation being real but unusable.

    `CONTEXT_ONLY_CITATION` is a conclusion resting on a one-hop neighbour -
    every reference exists, and none of them is the kind of thing a verdict
    can rest on. `SUPERSEDED_AS_GOVERNING` is the sharper case and it is this
    component's worst available output: a verdict resting on the decision the
    resolver considered and correctly rejected, which is legitimately in the
    package as context and looks completely normal.
    """


class EvidenceRole(StrEnum):
    """Why a piece of evidence is in a package.

    Also the truncation order when a package exceeds its budget: the rule text
    is kept longest, structural context dropped first.

    `PERMITTED_SET` is the one that evidences an absence. Under a default-deny
    policy the conclusion "nothing permits this" rests on a rule plus a
    silence, and a silence has no file and no line to cite. So the package
    carries what *is* permitted for the subject instead, and the conclusion
    becomes an observation over a finite list rather than an assumption.
    """

    RULE = "rule"
    RATIONALE = "rationale"
    SUPERSEDED = "superseded"
    PERMITTED_SET = "permitted_set"
    IMPLICATION = "implication"
    STRUCTURAL_CONTEXT = "structural_context"


@dataclass(frozen=True)
class Span:
    """Where a piece of evidence physically is.

    Carried so a citation can be shown to a reader rather than described to
    them. An evidence item nobody can point at is not evidence.
    """

    path: str
    start_line: int
    end_line: int

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
        }


@dataclass(frozen=True)
class FactEndpoint:
    """One end of an observed relationship, in its three forms.

    Three, because three different readers need three different things and
    deriving any of them later means a join somebody will get wrong:

      `canonical`  the identity. What a decision is matched against, and what
                   the fact's id is hashed from. Two spellings of one element
                   share this and nothing else.
      `name`       the name recovery used. What a person reads on a screen or
                   in a model's prompt; `payment-service`, not `payment`.
      `id`         recovery's own element id. What makes a fact traceable back
                   to the edge it came from in the input snapshot.

    Nested rather than six flat fields on the fact, so each meaning is named
    once instead of twice and an id cannot exist without the name beside it.
    """

    id: str
    name: str
    canonical: str

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "canonical": self.canonical}


@dataclass(frozen=True)
class ObservedFact:
    """One relationship in the architecture, as validation sees it.

    `fact_id` is a content hash of the triple plus the release, so the same
    relationship observed in two runs of the same release carries the same id
    and results can be compared without matching on position.

    `style_resolved` records which adapter produced this fact. When it is the
    generic adapter, the style could not be determined and `quality_ceiling`
    reflects that. `style_source` records whose answer that style was -
    recovery detected it, or validation inferred it - and travels on the fact
    rather than only on the run, because a fact can be read on its own and the
    strength of a verdict about it depends on the answer.

    `subject` and `object` are `FactEndpoint`s rather than strings. The
    canonical form is the identity and the only thing a rule may be matched
    on; the reported name and the element id travel beside it because a screen
    needs the first and traceability needs the second, and recovering either
    one afterwards means a join.

    `release_id` and `release_sort_key` are both carried, and both are needed.
    The string is what serialises and what C3 reads; the key is what orders,
    because `"v0.10.0" > "v0.9.0"` is false as text. Neither is derived from
    the other on demand - a reader that has to remember to sort by one field
    rather than the obvious one eventually forgets.
    """

    fact_id: str
    release_id: str
    release_sort_key: tuple[int, ...]
    subject: FactEndpoint
    relationship: RelationshipKind
    object: FactEndpoint
    style_resolved: str
    style_source: str
    quality: str
    attributes: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionRecord:
    """One architectural decision, valid over a range of releases.

    The validity interval is half-open - `valid_from` inclusive, `valid_to`
    exclusive - so a decision and the decision that supersedes it never both
    apply to the same release. `valid_to` of None means still in force.

    None of the seven provenance fields has a default. A record that cannot
    say where it came from, how strong that source is or how it was extracted
    cannot be built at all, which is the only reliable way to stop one
    appearing later with its origin quietly missing.

    `source` and `source_repository` are the two that answer questions the
    others cannot. Which adapter produced a record decides whether its absence
    from a later release means the rule was withdrawn, and which repository it
    was read from matters as soon as decisions live somewhere other than the
    code they describe.
    """

    decision_id: str
    subject: str
    constraint: ConstraintKind
    object: str
    valid_from: str
    valid_to: str | None

    source: str
    source_repository: str
    source_tier: SourceTier
    source_strength: EvidenceStrength
    source_ref: str
    extraction_method: ExtractionMethod
    extracted_at: datetime

    source_span: Span | None = None
    """Which lines of `source_ref` this rule was read from.

    Carried because evidence retrieval has to *quote* a rule rather than name
    the file it is in, and only whatever parsed the document knows the line.
    Reconstructing it later would mean a second parser for one file, which is
    two chances to disagree about what a rule is.

    `None` is legal and means there is no document: a decision ratified by an
    architect has a person behind it rather than a file.
    """

    rationale: str | None = None
    supersedes: str | None = None
    ratified_by: str | None = None
    ratified_at: datetime | None = None

    def to_event(self) -> dict:
        """Serialise for the append-only knowledge log."""

        return {
            "decision_id": self.decision_id,
            "subject": self.subject,
            "constraint": self.constraint,
            "object": self.object,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "source": self.source,
            "source_repository": self.source_repository,
            "source_tier": self.source_tier,
            "source_strength": self.source_strength,
            "source_ref": self.source_ref,
            "source_span": self.source_span.to_dict() if self.source_span else None,
            "extraction_method": self.extraction_method,
            "extracted_at": self.extracted_at.isoformat(),
            "rationale": self.rationale,
            "supersedes": self.supersedes,
            "ratified_by": self.ratified_by,
            "ratified_at": self.ratified_at.isoformat() if self.ratified_at else None,
        }


@dataclass(frozen=True)
class Resolution:
    """Which decision governs a fact at its release.

    Three outcomes, and they are not interchangeable. `governing` is one
    decision. `uncovered` means no decision speaks to this relationship, which
    is a finding about the subject system. `ambiguous` means two decisions
    apply and neither supersedes the other - reported as it stands rather than
    resolved by a tiebreak, because an invented tiebreak cannot be shown to be
    right.

    All three skip the model entirely except `governing`: there is nothing to
    reason about without a rule to reason against.

    `superseded_ancestor` is what lets the answer be shown rather than
    asserted - the decision that was considered and correctly rejected.
    Resolving to the right record while forgetting the one it replaced is a
    right answer nobody can defend.

    `conflicting_sources` names the sources that described this relationship
    differently from the one that governs. A written decision and a running
    configuration disagreeing is a finding about the system under study, so it
    travels with the answer instead of being dropped on the way.
    """

    governing: DecisionRecord | None
    uncovered: bool = False
    ambiguous: bool = False
    candidates: tuple[str, ...] = ()
    superseded_ancestor: str | None = None
    conflicting_sources: tuple[str, ...] = ()

    superseded: DecisionRecord | None = None
    """The record the governing one replaced, not just its id.

    Carried whole because the demonstration has to *show* that the earlier
    decision was considered and correctly rejected, and showing it means
    quoting the lines it came from. The resolver has the version in hand when
    it works the ancestor out; anything downstream would have to replay the
    log to get it back, and a stage that can re-read the log can answer a
    different question from the one it was asked.
    """

    permitted_instead: tuple[DecisionRecord, ...] = ()
    """What *is* permitted, when the answer rests on what is not.

    Only filled when the governing decision is the general refusal. "Nothing
    permits this" has no file and no line, so the evidence for it is the
    finite list that does not contain the pair in question - which a reader
    can check rather than having to trust.
    """


@dataclass(frozen=True)
class EvidenceItem:
    """One piece of evidence, with somewhere to point.

    `ref` is what the model must cite and what the citation guard checks
    against, so every item has one and no two items share one.

    `span` is where the text physically is, and it is optional because not
    every piece of evidence is a quotation. A rule read from a policy document
    has lines; a statement that two sources described one relationship
    differently is derived from the resolution and has none. An item without a
    span is still citable and still checkable - it is only unquotable.
    """

    ref: str
    role: EvidenceRole
    text: str
    span: Span | None = None


@dataclass(frozen=True)
class EvidencePackage:
    """Everything the model is allowed to reason from, for one fact.

    `evidence_hash` is computed over the canonicalised package and is what
    makes a verdict cacheable and reproducible. It must not change between two
    runs over the same release, so anything assembled here has to be ordered
    deterministically.

    `truncated` is published rather than silent. A package that quietly drops
    items produces a verdict that cannot be explained, and a package that
    truncates differently between runs would miss the cache without saying so.

    `subject`, `relationship`, `object` and `release_id` are the question this
    is evidence *for*, in the names a person reads. They are carried because
    the reasoner's renderer is handed the package and nothing else - one that
    could reach the fact would be reading evidence that was never sealed - and
    a packet of evidence that cannot state its own question is a riddle rather
    than a question.

    They are deliberately **not** part of `evidence_hash`. `fact_id` is
    hashed, and it is derived from this same triple and release, so adding
    them would change every hash already recorded while discriminating between
    nothing the fact id does not already separate.
    """

    fact_id: str
    subject: str
    relationship: RelationshipKind
    object: str
    release_id: str
    evidence_hash: str
    items: tuple[EvidenceItem, ...]
    truncated: bool = False
    dropped_roles: tuple[EvidenceRole, ...] = ()

    @property
    def refs(self) -> frozenset[str]:
        """Every citable reference in this package.

        The reasoner's citations are checked against this set. A schema can
        require a citation to be present and well formed; only this comparison
        can establish that it refers to something real.
        """

        return frozenset(item.ref for item in self.items)


@dataclass(frozen=True)
class AIResult:
    """One model response, with everything needed to reproduce it."""

    content: dict
    model_id: str
    prompt_version: str
    schema_mode: str
    cached: bool
    task: str


@dataclass(frozen=True)
class PromptTemplate:
    """One versioned prompt, already loaded.

    `version` is the field that does the work: it is part of the cache key and
    it is what a published result is attributed to. `v1` is never edited once
    results exist - a changed prompt is `v2` - which is also what makes the
    paraphrase-robustness arm a second file rather than a rewrite.

    The component holds the shape and never the file. Loading happens in
    infrastructure and the template is passed in, so a prompt stays a
    reviewable text artifact without any component learning how to open one.
    """

    version: str
    system: str
    body: str


@dataclass(frozen=True)
class ArbiterCheck:
    """What the deterministic table concluded about one fact.

    Two fields, deliberately. `verdict` is `CONFIRMS`, `CONTRADICTS` or
    `None`, and `None` is an abstention with a reason rather than a failure:
    an oracle that answers everything is not an oracle.

    `basis` names the row of the table that was used and is never empty, for
    either answer. It is published because a mechanical verdict looks
    authoritative and is only as good as the rule extraction above it - so the
    row sits on screen beside the conclusion where it can be argued with,
    rather than being a number nobody can question.
    """

    verdict: Verdict | None
    basis: str


@dataclass(frozen=True)
class PrimaryVerdict:
    """The reasoner's conclusion about one fact.

    `cited_evidence_refs` must be non-empty and every entry must exist in the
    package the verdict was produced from. A verdict citing nothing, or citing
    something absent, is rejected rather than recorded - which is the component's
    only real guarantee that a conclusion is grounded in its evidence.
    """

    fact_id: str
    verdict: Verdict
    reasoning: str
    cited_evidence_refs: tuple[str, ...]
    model_id: str
    prompt_version: str
    evidence_hash: str
    cached: bool
    retried: bool = False

    provider: str = ""
    schema_mode: str = ""
    """What answered, and under what enforcement.

    Two runs on two providers, or one in strict mode and one best-effort, are
    not the same experiment, and a result that cannot say which it was cannot
    be compared with the other. Provenance is also the one thing that cannot
    be added to results afterwards.
    """

    produced_by: VerdictSource = VerdictSource.MODEL
    arbiter: ArbiterCheck | None = None
    arbiter_agreement: ArbiterAgreement | None = None
    """What checked this verdict, and whether it agreed.

    `arbiter` is the table's own answer with the row it used, kept beside the
    model's rather than instead of it: overwriting would make the model
    decoration and would throw away the only data that could ever show the
    table itself to be wrong.

    `arbiter_agreement` is null when there is no comparison to report, which
    is the case on a verdict the arbiter produced alone - it was the verdict,
    so there is nothing to compare it with. `NOT_CHECKED` means something
    else: that the table abstained.
    """

    guard_failures: tuple[GuardFailure, ...] = ()
    """Which guards rejected an answer before this one was accepted.

    Kept even when the retry succeeded. A malformed response and an invented
    citation have different fixes, and the rate of the second one is a result
    about the model rather than an incident in a log.
    """

    ladder_rung: int = 1
    """Which rung of the fallback ladder produced this verdict.

    0 is the cache, 1 the configured model, 2 its identical retry, 3 and 4 the
    models tried when nothing answered, 5 the arbiter alone and 6 nothing at
    all. Published because `model_id` alone cannot distinguish a first answer
    from a retried one, and a run that fell down the ladder and looked like a
    normal run is the failure this component exists to prevent.
    """

    @property
    def disagreement_note(self) -> str:
        """One sentence for a screen, when the table and the model disagree.

        Derived rather than stored, so it cannot drift from the two fields it
        describes. Empty whenever there is no disagreement to report, which is
        what lets a template print it unconditionally.
        """

        disagreed = self.arbiter_agreement is ArbiterAgreement.DISAGREED
        if self.arbiter is None or not disagreed:
            return ""

        return (
            f"The model answered {self.verdict} and the deterministic table "
            f"answered {self.arbiter.verdict}: {self.arbiter.basis}."
        )


class ObjectionKind(StrEnum):
    """The four faults the verifier is asked to look for.

    Closed and small for the same reason the relationship vocabulary is: free
    text cannot be counted, so *which kind of reasoning error does a free
    model make* would stay unanswerable over a corpus. `Objection.statement`
    is free text, so the evidence for a fifth kind would be visible in the
    results before the vocabulary were widened.

    The first two are about one item in the package; the last two are about
    the argument as a whole. That split is what decides whether a reference
    is required.
    """

    CITATION_DOES_NOT_SUPPORT = "citation_does_not_support"
    OVERLOOKED_EVIDENCE = "overlooked_evidence"
    CLAIM_EXCEEDS_EVIDENCE = "claim_exceeds_evidence"
    UNSTATED_ASSUMPTION = "unstated_assumption"


OBJECTIONS_ABOUT_ONE_ITEM = (
    ObjectionKind.CITATION_DOES_NOT_SUPPORT,
    ObjectionKind.OVERLOOKED_EVIDENCE,
)
"""The two kinds that have an item to name.

A citation that does not say what was claimed, and an item that argues the
other way and was not cited, are both statements about one reference. A claim
exceeding its evidence and an assumption that came from nowhere are
statements about the whole argument, and a reference required for those would
be attached to an arbitrary item while reading as precise.
"""


@dataclass(frozen=True)
class Objection:
    """One fault the verifier found in the argument for a verdict.

    A reference is required for the two kinds that are about one item and may
    be absent for the two that are not. Both halves are enforced here rather
    than asked for in a prompt, because inventing a reference to satisfy a
    type is the one lie this subcomponent cannot afford: the objection would
    point at the wrong item and look specific while doing it.

    Raising rather than repairing puts an ordering requirement on the caller.
    A model response is checked by the guards *before* it becomes objections,
    so a missing reference is a recorded guard failure and one retry rather
    than an exception out of a parser.
    """

    kind: ObjectionKind
    ref: str | None
    statement: str

    def __post_init__(self) -> None:
        if self.kind in OBJECTIONS_ABOUT_ONE_ITEM and not self.ref:
            raise ValueError(
                f"An objection of kind {self.kind} is about one evidence item, "
                "so it has to name the item."
            )

    def to_dict(self) -> dict:
        """The form a stored or published objection takes.

        Here rather than beside whoever writes it out, because an objection
        that cannot serialise itself gets a serialiser written next to the
        first consumer and a second one next to the next, and the two
        disagree about whether an absent reference is `null` or missing.
        """

        return {"kind": self.kind, "ref": self.ref, "statement": self.statement}


@dataclass(frozen=True)
class BlindVerdict:
    """The verifier's own verdict, reached without being shown the primary's.

    **A separate type from `PrimaryVerdict` on purpose, and the reason is the
    one thing this arm must never do.** Its content is a verdict in the same
    five-word vocabulary, so it would fit `PrimaryVerdict` exactly - and then
    nothing in the type system would stop an unanchored second opinion being
    published as the component's conclusion about a dependency. It is evidence
    *about the models*, never about the architecture.

    It carries no arbiter fields for the same reason. The deterministic table
    is compared against the verdict that was published, once, in M4. Comparing
    it against this one as well would produce a second agreement rate that
    looks like the first and means something different.

    `mechanism` is recorded so results from different weeks stay comparable
    when the mechanism itself becomes the thing under study.
    """

    fact_id: str
    verdict: Verdict
    reasoning: str
    cited_evidence_refs: tuple[str, ...]
    evidence_hash: str
    model_id: str
    prompt_version: str
    cached: bool
    mechanism: str = ""
    provider: str = ""
    schema_mode: str = ""
    retried: bool = False
    guard_failures: tuple[GuardFailure, ...] = ()

    def agrees_with(self, verdict: "PrimaryVerdict") -> bool:
        """Whether this blind verdict reached the same conclusion.

        A comparison of two words, not a model's opinion about agreement.
        Asking a model whether two verdicts agree would add a third thing that
        can be wrong to a measurement whose whole point is that only one
        variable moved.

        Raises when the two did not come from the same evidence. The anchoring
        delta is only interpretable if both arms answered the identical
        question, and two verdicts over two packages compare perfectly well
        while meaning nothing - so this refuses rather than returning a
        number somebody would publish.
        """

        if self.evidence_hash != verdict.evidence_hash:
            raise ValueError(
                f"Cannot compare arms for fact '{self.fact_id}': the blind "
                f"verdict saw evidence {self.evidence_hash[:12]} and the "
                f"primary saw {verdict.evidence_hash[:12]}. An agreement rate "
                f"across two different packages measures nothing."
            )
        return self.verdict is verdict.verdict


@dataclass(frozen=True)
class Verification:
    """The verifier's response to a primary verdict.

    `mechanism` is recorded so results from different weeks stay comparable
    when the mechanism itself becomes the thing under study. Two string fields
    now save building a separate harness per mechanism later.
    """

    fact_id: str
    outcome: VerificationOutcome
    mechanism: str
    reasoning: str
    model_id: str
    prompt_version: str
    cached: bool

    objections: tuple[Objection, ...] = ()
    """What the verifier found wrong, in the closed four-kind vocabulary.

    Empty on agreement and non-empty on disagreement - a correspondence that
    is checked in plain Python rather than trusted, because a small model
    asked for a list of faults and a judgement in one response will sometimes
    write three objections and then conclude `agree`.

    This is also the only part of this output a person can act on. `AGREE`
    tells an architect nothing; *the cited line permits one element and this
    verdict is about another* tells them where to look.
    """

    evidence_hash: str = ""
    """The package this verification was produced from.

    Asserted equal to the verdict's. Without it nothing in the output would
    say whether both passes saw the same evidence, and a verification of a
    *different* package is not a verification - it is a second opinion on a
    different question, and it would look exactly the same.
    """

    challenged_model_id: str = ""
    """The model whose answer this verification was about.

    Recorded here rather than left to a join, because the run stamp carries
    the *configured* reasoner and this carries the one that actually answered
    - and those differ exactly when it matters. A verdict that fell to the
    ladder's second model, or to the deterministic table with a model id of
    "none", was produced by something other than the configured reasoner, and
    a mechanism comparison that assumed otherwise would be comparing arms
    that were never run against the same thing.

    With `mechanism` beside it, one row says which mechanism challenged which
    model, which is what makes the four-arm comparison a configuration change
    rather than a harness per arm.
    """

    provider: str = ""
    schema_mode: str = ""
    retried: bool = False
    guard_failures: tuple[GuardFailure, ...] = ()
    """What answered, under what enforcement, and what was rejected first.

    The same four fields the verdict carries, for the same reason: two runs
    under different enforcement are not the same experiment, and provenance
    is the one thing that cannot be added to a result afterwards.

    `guard_failures` is kept even when the retry succeeded. An incoherent
    answer and an invented reference have different fixes, and the rate of
    each is a result about the model rather than an incident in a log.
    """


@dataclass(frozen=True)
class ScoreTrace:
    """The arithmetic behind a confidence value.

    Published because a bare number invites exactly one question that cannot
    otherwise be answered. With its terms beside it the number stops being a
    claim about accuracy and becomes a calculation anyone can check.
    """

    terms: dict
    total: float
    ceiling_applied: str | None = None

    def to_dict(self) -> dict:
        return {
            "terms": dict(self.terms),
            "total": self.total,
            "ceiling_applied": self.ceiling_applied,
        }


@dataclass(frozen=True)
class ClassifiedFact:
    """A fact with its final bucket, confidence and route.

    `model_calls` is counted rather than assumed. An uncovered or ambiguous
    fact reaches its bucket with zero calls, and being able to show that is
    what distinguishes a system that knows when not to use a model from one
    that calls a model for everything.
    """

    fact_id: str
    bucket: str
    confidence: float
    score_trace: ScoreTrace
    route: str
    governing_decision: str | None
    source_tier: SourceTier | None
    evidence_refs: tuple[str, ...]
    model_calls: int
    source_element_id: str = ""
    target_element_id: str = ""
    relationship: str = ""
    attributes: dict = field(default_factory=dict)
    """Which relationship this verdict is about, in recovery's own ids.

    Carried here because the published graph puts every verdict on the edge it
    describes, and the publisher is handed classified facts and nothing else.
    Without these it would have to be given the observed facts as well and
    join the two lists by `fact_id` - and a join between two lists that are
    supposed to describe the same thing is exactly what publishing the verdict
    on the edge exists to avoid.
    """

    verdict: "PrimaryVerdict | None" = None
    verification: "Verification | None" = None
    """Both model outputs, kept rather than reduced to a word.

    The reasoning sentence and the objections are the only parts of the output
    a model actually produced, and a result that cannot show them is an
    assertion rather than evidence. They are also what the relational model
    exists for: *did the two models fail on the same facts* is a join between
    the two, and it is impossible once either is reduced to its verdict.

    They do not reach the consuming component. The published edge carries the
    three badge fields below and nothing else - which is a decision about what
    crosses a boundary, not about what is worth storing.
    """

    produced_by: str = ""
    verification_outcome: str | None = None
    arbiter_agreement: str | None = None
    """Which of the three judges produced this, and what the other two said.

    A fact that reaches a consumer without them can still be read, but a study
    that averages a rule-only verdict with a three-judge one is averaging two
    different things. They are set here rather than left on the verdict
    because the verdict does not cross the component boundary and this does.
    """


@dataclass(frozen=True)
class ReviewItem:
    """One fact waiting on an architect.

    Holds references, never copies. The evidence and the candidate decision
    live in the knowledge log and the run artifacts; a second copy here would
    be the one that goes stale, and there would be no way to tell which was
    right.
    """

    item_id: str
    fact_id: str
    bucket: str
    confidence: float
    source_tier: SourceTier | None
    evidence_refs: tuple[str, ...]
    candidate_decision_id: str | None
    created_at: datetime
    status: str = "pending"


class StageStatus(StrEnum):
    """How one pipeline stage ended.

    `SKIPPED` is a real outcome rather than a failure: a stage that had nothing
    to do because an earlier stage short-circuited is not the same as a stage
    that ran and found nothing.

    `PENDING` is the same distinction one step earlier: a stage whose
    subcomponent is not written yet has not failed, and a run that reaches the
    end with stages pending is the honest description of a component being
    built in sequence. It can only arise while subcomponents are still stubs,
    and stops arising once the last one is implemented.
    """

    COMPLETED = "completed"
    SKIPPED = "skipped"
    PENDING = "pending"
    FAILED = "failed"


@dataclass(frozen=True)
class StageRecord:
    """What one subcomponent did during a run.

    Published as a list rather than keyed by stage name. A list keeps the
    pipeline's shape out of every consumer's type definitions, so adding or
    reordering a stage stays a change here and nowhere else.

    `note` and `warnings` are different things and are kept apart. The note
    says something about the stage - why it was skipped, what stopped it, how
    it resolved the style - and there is at most one. The warnings are what
    the stage observed about the *architecture*: names that collapsed into one
    identity, relationships that named an element nobody declared. A
    subcomponent that reports one of those and has it dropped on the way out
    has reported nothing, which is why they are published rather than logged.
    """

    name: str
    status: StageStatus
    counts: dict = field(default_factory=dict)
    duration_ms: int = 0
    note: str | None = None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "counts": dict(self.counts),
            "duration_ms": self.duration_ms,
            "note": self.note,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ValidationRunResult:
    """One complete validation run.

    `model_calls` is totalled across the run so the cost of a run is visible
    without adding up the facts, and so a run that should have made no calls
    can be shown to have made none.

    `style_resolved` and `style_source` are on the run as well as on every
    fact, and both are `None` when normalisation did not run. They are here
    because they describe the whole run rather than one relationship: one
    answer decided which adapter produced every fact in it, and a reader
    looking at a result should not have to open a fact to find out whose
    answer that was.
    """

    run_id: str
    repository_id: str
    release_id: str
    status: str
    stages: tuple[StageRecord, ...]
    facts: tuple[ClassifiedFact, ...] = ()
    published_ref: str | None = None
    model_calls: int = 0
    validation_confidence: float = 0.0
    """The mean per-fact confidence over this release, and the figure the next
    component gates on.

    A release-level aggregate rather than a verdict about the release: it is
    the mean of numbers whose own arithmetic each fact publishes, so it can be
    checked by hand from the output. Read it with the classification stage's
    `facts` count beside it - 0.0 over no facts and 0.0 over fifteen bad ones
    are different situations and the number alone cannot tell them apart.
    """

    style_resolved: str | None = None
    style_source: str | None = None
    verification_arm: str | None = None
    """What the verifier was shown on this run: `informed`, `blind` or `both`.

    Null when verification did not run, for the same reason
    `verification_mode` is: a question that did not arise has no answer. The
    two fields are separate axes - whether the check happened, and what it was
    given - and a reader needs both to know what an agreement rate is worth.
    """

    verification_mode: str | None = None
    """Whether this run asked a second model, and if not, why not.

    One of `VerificationMode`'s three values, and `None` when no fact reached
    verification at all - an uncovered release has nothing to verify, and
    saying `performed` or `unavailable` about it would both be false. The same
    shape as `style_resolved`: null means the question did not arise.

    On the run because it changes how every number under it should be read,
    which is why the summary card states it in words above the counts.
    """

    generated_at: datetime | None = None
    """When this run produced its answer, which is not when the release was cut.

    Both are published and they are routinely weeks apart. A consumer ordering
    releases by this one would be ordering them by when somebody happened to
    run the validator.
    """

    released_at: datetime | None = None
    released_at_source: str | None = None
    """When the release this run validated was actually cut, and from where.

    A parameter of the run rather than something read here: reading git
    history is the same category of thing as reading source code, which this
    component also does not do. `None` is published as `None` - a plausible
    wrong date orders a timeline wrongly and cannot be told apart from a right
    one.

    `released_at_source` is one of `tagger`, `author` or `caller`, and it is
    published so that a suspicious ordering downstream is traceable to the
    field that produced it. The committer date is deliberately never one of
    them: it is rewritten by every rebase and reads as today.
    """

    reasoner_model: str | None = None
    verifier_model: str | None = None
    prompt_versions: tuple[str, ...] = ()
    """Which models answered and under which prompts, as the run observed it.

    Not the configured models. The two differ exactly when it matters: a run
    that fell down the ladder was answered by something other than the
    configured reasoner, and a result that cannot say what produced it is an
    anecdote rather than a measurement.
    """

    decision_mode: str | None = None
    """Where this run's decisions came from.

    On the run because it describes the whole of it: one answer decided what
    every verdict in it was judged against. Published rather than inferred,
    so a reader can always tell whether a result rests on decisions somebody
    wrote or on rules this component reconstructed.
    """
