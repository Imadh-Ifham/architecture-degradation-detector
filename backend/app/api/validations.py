"""Architecture validation endpoints.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Exposes the architecture validation component over HTTP: describe the
    pipeline, and run it over one release of an ingested repository.

    This module is the component's composition root. It is the only place that
    knows which implementation of each port is wired in, which is what lets
    the component read recovery's real output here and a committed fixture in a
    test without either side changing.

    A run returns its stage records whether or not every stage is implemented.
    While the component is being built in sequence that is the useful answer:
    the stages that are finished report what they did, and the rest report
    themselves as pending rather than failing the request.

    Everything a reader needs is written for the generated OpenAPI document
    rather than kept here. Each route carries its summary and the meaning of
    every status code it can return, and each request model carries an example
    body, so `/docs` can be driven without this file open beside it. The
    schema is generated from these models, which is the point: a response
    documented separately from the code that produces it is a response that
    eventually describes something else.
"""

import time
from datetime import UTC, datetime
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.components.architecture_recovery.repository_ingestion.service import (
    SOURCE_DIRECTORY_NAME,
)
from app.components.architecture_validation import (
    PIPELINE,
    ArchitectureValidationService,
)
from app.components.architecture_validation.architect_review import (
    ArchitectReviewService,
    QueueUnavailable,
)
from app.components.architecture_validation.architect_review.models import (
    ReviewDecision,
)
from app.components.architecture_validation.classification import ClassificationService
from app.components.architecture_validation.decision_knowledge import (
    DEFAULT_MODE,
    DecisionKnowledgeService,
    DecisionSourceError,
    NoDecisionsAvailable,
    SourceRequest,
)
from app.components.architecture_validation.evidence_retrieval import (
    EvidenceRetrievalService,
)
from app.components.architecture_validation.graph_publishing import (
    GraphPublishingService,
)
from app.components.architecture_validation.independent_verification import (
    IndependentVerificationService,
)
from app.components.architecture_validation.observation_normalization import (
    ObservationNormalizationService,
    UnorderableRelease,
    release_sort_key,
)
from app.components.architecture_validation.validation_reasoning import (
    ValidationReasoningService,
)
from app.core.config import settings
from app.domain.recovered_architecture import IncoherentArchitecture
from app.domain.validated_architecture import ReleaseDateSource
from app.infrastructure.ai import (
    SCHEMA_MODE_STRICT,
    TASK_NARRATION,
    TASK_PRIMARY_VERDICT,
    TASK_PRIMARY_VERDICT_FALLBACK,
    TASK_PRIMARY_VERDICT_LOCAL,
    TASK_VERIFICATION,
    CallLog,
    ConfiguredAIClient,
    ModelTranscriptFileStore,
    NarrationUnavailable,
    RunNarrator,
    ai_settings,
    load_prompt,
    summarise,
)
from app.infrastructure.ai.providers.openai_compatible import (
    OpenAICompatibleProvider,
    ProviderError,
)
from app.infrastructure.decision_log import JsonlDecisionStore
from app.infrastructure.git.release_dates import ReleaseDateReader
from app.infrastructure.git.workspace_artifact_reader import (
    ArtifactUnavailableError,
    WorkspaceArtifactReader,
)
from app.infrastructure.recovery_gateway import (
    GraphContractError,
    GraphStoreReader,
    InventoryContractError,
    InventoryFileArchitectureReader,
    SnapshotContractError,
    SnapshotFileReader,
    WorkspaceIndex,
    WorkspaceUnavailable,
)
from app.infrastructure.validated_graph import ValidatedGraphFileStore

router = APIRouter(prefix="/validations", tags=["Validation"])

PRIMARY_VERDICT_PROMPT = "primary_verdict.v1.md"
CRITICAL_REFRAMING_PROMPT = "critical_reframing.v1.md"
BLIND_VERDICT_PROMPT = "blind_verdict.v1.md"
RUN_NARRATIVE_PROMPT = "run_narrative.v1.md"

REASONING_TASKS = (
    TASK_PRIMARY_VERDICT,
    TASK_PRIMARY_VERDICT_FALLBACK,
    TASK_PRIMARY_VERDICT_LOCAL,
)
"""The reasoner's ladder, in the order it is climbed.

The order is wiring rather than reasoning, so it is decided here: the
subcomponent is handed task names and never learns which models answer them.
"""


class StageDescriptionResponse(BaseModel):
    """One stage of the pipeline, and how far it has been built."""

    name: str = Field(description="The subcomponent's folder name.")
    order: int = Field(description="Position in the run, starting at 1.")
    role: str = Field(description="What the stage does, in one sentence.")
    research_module: str | None = Field(
        description="The module in the research design, M1 to M8, or null for "
        "a stage with no module behind it."
    )
    uses_model: bool = Field(
        description="Whether this stage calls a language model. Two of the "
        "nine do; every other stage is deterministic code."
    )
    implemented: bool = Field(
        description="Whether the subcomponent is written. A client renders "
        "build progress from this rather than hard-coding it."
    )


class PipelineResponse(BaseModel):
    """The pipeline's shape, for a client that has no run to show yet."""

    stage_count: int = Field(description="How many stages the pipeline has.")
    implemented_count: int = Field(description="How many of them are written.")
    stages: list[StageDescriptionResponse] = Field(description="In run order.")


class StageRecordResponse(BaseModel):
    """What one stage did during a run.

    `counts` is deliberately open: each stage counts different things, and
    naming them all here would mean editing this schema every time a stage
    learns to count something new.
    """

    name: str = Field(description="The stage, matching the pipeline description.")
    status: str = Field(
        description=(
            "completed - it ran. skipped - it had nothing to do because an "
            "earlier stage short-circuited. pending - its subcomponent is not "
            "written yet. failed - it ran and raised."
        ),
        examples=["completed"],
    )
    counts: dict[str, int] = Field(
        default_factory=dict,
        description="Whatever this stage counts. Keys differ per stage.",
        examples=[{"facts": 15, "relationships": 15}],
    )
    duration_ms: int = Field(description="Wall-clock time inside the stage.")
    note: str | None = Field(
        default=None,
        description="Why the stage was skipped, left pending, or failed.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "What this stage observed about the architecture, as opposed to "
            "about itself - names that collapsed into one identity, "
            "relationships naming an element nobody declared. Empty is the "
            "expected value; a non-empty list is a finding about the subject "
            "system rather than a fault here."
        ),
        examples=[
            [
                "element names ['cart', 'cart-service'] all reduce to the "
                "identity 'cart'; they are treated as one element"
            ]
        ],
    )


class ValidationRunResponse(BaseModel):
    """One validation run, stage by stage."""

    run_id: str = Field(description="Identifies this run.")
    repository_id: str
    release_id: str
    status: str = Field(
        description=(
            "completed - every stage ran. incomplete - at least one stage is "
            "not written yet, so this is a partial run and must not be read "
            "as a finished one. failed - a stage raised."
        ),
        examples=["incomplete"],
    )
    model_calls: int = Field(
        description="Model calls made across the whole run. Counted rather "
        "than assumed, so a run that should have made none can be shown to "
        "have made none."
    )
    validation_confidence: float = Field(
        default=0.0,
        description=(
            "The mean per-fact confidence across this release. Read it with "
            "the classification stage's 'facts' count beside it: 0.0 over no "
            "facts and 0.0 over fifteen weak ones are different situations."
        ),
        examples=[0.78],
    )
    published_ref: str | None = Field(
        default=None,
        description="Where the validated graph was published, once the "
        "publishing stage runs.",
    )
    style_resolved: str | None = Field(
        default=None,
        description=(
            "The architectural style every fact in this run was normalised "
            "as. 'generic' means it could not be determined, which caps how "
            "strong any verdict in the run may become."
        ),
        examples=["microservices"],
    )
    style_source: str | None = Field(
        default=None,
        description=(
            "Whose answer that style was. 'c1' means recovery detected it and "
            "it was taken as given. 'inferred_by_c2' means recovery supplied "
            "none and this component worked it out from the elements."
        ),
        examples=["inferred_by_c2"],
    )
    verification_arm: str | None = Field(
        default=None,
        description=(
            "What the verifier was shown on this run: informed, blind or "
            "both. Null when verification did not run. A separate axis from "
            "verification_mode, which says whether it ran at all - an "
            "agreement rate cannot be read without both."
        ),
    )
    verification_mode: str | None = Field(
        default=None,
        description=(
            "Whether a second model checked this run's verdicts. performed - "
            "it did. not_requested - the caller turned it off. unavailable - "
            "it could not be reached, which is a fault in the environment "
            "rather than a result, and is not agreement. Null when no fact "
            "reached verification at all. This line changes how every count "
            "under it should be read, which is why it is reported beside "
            "them rather than inferred from them."
        ),
    )
    decision_mode: str | None = Field(
        default=None,
        description=(
            "Where this run's decisions came from. Every verdict in the run "
            "was judged against what this mode supplied, so it travels with "
            "the result rather than being remembered."
        ),
        examples=["combined"],
    )
    stages: list[StageRecordResponse] = Field(
        description="One record per stage, in run order."
    )


class ValidationRunRequest(BaseModel):
    """Which release of which ingested repository to validate.

    The release is named by the caller. Recovery identifies a working tree by
    commit, and commit hashes carry no order, which the validity intervals in
    the decision history need.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "repository_id": "online-boutique",
                    "release_id": "v0.10.0",
                    "decision_mode": "combined",
                }
            ]
        }
    )

    repository_id: str = Field(
        min_length=1,
        description="The repository as recovery ingested it.",
    )
    decision_mode: Literal["repo_adr", "external_adr", "combined"] = Field(
        default=DEFAULT_MODE,
        description=(
            "Where the decisions to validate against come from. repo_adr - "
            "decision records kept in this repository. external_adr - records "
            "kept in a separate repository, named below. combined - that "
            "repository plus rules reconstructed from this one's "
            "configuration, which is the only mode that produces a result on "
            "a repository holding no decision records. Recorded on the run, "
            "so every verdict can be traced to the kind of evidence behind it."
        ),
    )
    adr_repository_id: str | None = Field(
        default=None,
        description=(
            "The separate decision repository, as ingestion cloned it. "
            "Required by the modes that read one; a mode that cannot run "
            "reports that rather than reporting zero decisions."
        ),
    )
    arm: Literal["informed", "blind", "both"] = Field(
        default="informed",
        description=(
            "What the verifying model is shown. informed - the evidence and "
            "the first model's verdict, and it reports what is wrong with "
            "the argument. This is the default and the only arm that "
            "produces objections an architect can act on. blind - the "
            "evidence and not the answer, which buys an unanchored second "
            "verdict and nothing to act on. both - three model calls per "
            "fact, where the gap between the two agreement rates is how much "
            "being shown the answer moves the second model. both is a "
            "measurement mode and not a demonstration one."
        ),
    )
    verify: bool = Field(
        default=True,
        description=(
            "Whether to ask a second model whether each verdict's argument "
            "holds up. True is the default. False roughly halves the model "
            "calls and the wall-clock time of a run, and is published as a "
            "skip giving that reason - never as a verdict that passed an "
            "unperformed check. The primary verdicts are not re-paid for on a "
            "later verifying run, because the response cache is keyed on the "
            "evidence rather than on the run."
        ),
    )
    release_id: str = Field(
        min_length=1,
        description=(
            "A version tag, with or without a leading v. It has to order "
            "against other releases - a date stamp or a build label is "
            "refused, because the decision history compares releases to each "
            "other rather than to a calendar."
        ),
    )

    released_at: datetime | None = Field(
        default=None,
        description=(
            "When this release was actually cut. Optional: the tag's own date "
            "is read from the ingestion workspace when it can be, and a "
            "release whose date cannot be established publishes none rather "
            "than a guess. Supply it when the repository is not cloned "
            "locally, or to override what the tag says."
        ),
        examples=["2025-04-01T00:00:00Z"],
    )

    @field_validator("release_id")
    @classmethod
    def must_be_orderable(cls, value: str) -> str:
        """Refuse a release identifier that cannot be placed in order.

        Checked here as well as inside the component, using the component's
        own function rather than a second implementation of it. The component
        raises because no caller may hold facts that cannot be compared; this
        checks earlier only so that the failure arrives attached to the field
        that caused it, before anything is read from disk.
        """

        try:
            release_sort_key(value)
        except UnorderableRelease as error:
            raise ValueError(str(error)) from error
        return value


@lru_cache
def get_architecture_reader():
    """Provide the reader the configured architecture source names.

    Two sources, selected explicitly rather than by falling back from one to
    the other. A silent fallback would mean a run could be labelled as read
    from recovery's live output when it was read from a recording, and nothing
    in the result would say which - so the choice is configuration, and the
    reader's name is stamped on the run's provenance either way.
    """

    if settings.architecture_source == "graph":
        return GraphStoreReader(
            get_architecture_graph_store(), settings.repositories_root
        )
    if settings.architecture_source == "snapshot":
        return SnapshotFileReader(settings.snapshot_root)
    if settings.architecture_source == "inventory":
        return InventoryFileArchitectureReader(settings.repositories_root)

    raise ValueError(
        f"architecture_source is '{settings.architecture_source}'; "
        "expected 'graph', 'snapshot' or 'inventory'."
    )


@lru_cache(maxsize=1)
def get_architecture_graph_store():
    """Recovery's historical graph, as the live reader asks it.

    Imported inside the function so that a machine with no graph database
    configured can still start, and still run against a recording. The driver
    is built when the live reader is the one wired in and never otherwise.
    """

    from app.infrastructure.neo4j.architecture_snapshot_store import (
        Neo4jArchitectureSnapshotStore,
    )
    from app.infrastructure.neo4j.database import driver

    # The driver's own `session`, which is a context manager per operation.
    # The request-scoped dependency beside it yields one already open, and
    # the store opens its own.
    return Neo4jArchitectureSnapshotStore(driver.session)


@lru_cache
def get_artifact_reader() -> WorkspaceArtifactReader:
    """Provide the reader the decision sources read repository files through.

    The decision sources parse text and never open a file, so the composition
    root is where the workspace layout is known: ingestion keeps a clone's
    working tree one level inside the repository's own directory, and that is
    this function's knowledge rather than the reader's or the component's.
    """

    return WorkspaceArtifactReader(
        settings.repositories_root, checkout_subdirectory=SOURCE_DIRECTORY_NAME
    )


@lru_cache
def get_decision_store() -> JsonlDecisionStore:
    """Provide the log the decision history accumulates in.

    One file per repository, under the ignored artifacts directory, because
    the history is something a run produces. The corpus the demonstration is
    rehearsed against is a committed fixture read through the same port.
    """

    return JsonlDecisionStore(settings.decision_log_root)


@lru_cache
def get_ai_client() -> ConfiguredAIClient:
    """Provide model access, configured from the environment.

    Built even when no key is set, and that is deliberate. The reasoner's
    ladder ends at a deterministic arbiter, so a run on a machine with no key
    still produces a verdict for every governed fact and says on every one of
    them that no model was involved - which is more useful than refusing to
    start, and it is the demonstration's rollback.

    The second adapter is the local rung's, and it is built only when an
    endpoint for it is configured. A local runtime differs from the hosted one
    in the URL alone, which is why one adapter class serves both; and without
    the second adapter the rung's model id would be posted to the hosted
    provider, which does not serve it.
    """

    local = ai_settings.ai_local_base_url
    return ConfiguredAIClient(
        OpenAICompatibleProvider(
            base_url=ai_settings.ai_base_url,
            api_key=ai_settings.ai_api_key,
            timeout_seconds=ai_settings.ai_timeout_seconds,
        ),
        settings=ai_settings,
        local_provider=(
            OpenAICompatibleProvider(
                base_url=local,
                api_key=ai_settings.ai_api_key,
                timeout_seconds=ai_settings.ai_timeout_seconds,
            )
            if local
            else None
        ),
        call_log=get_call_log(),
    )


@lru_cache(maxsize=1)
def get_call_log() -> CallLog:
    """One log for the process, collecting only inside a capture block.

    Cached like the client it is handed to, because the two have to be the
    same pair: a second log would be wired to nothing and would report every
    run as having called no model, which is the exact false statement this
    whole path exists to make impossible.
    """

    return CallLog()


@lru_cache(maxsize=1)
def get_transcript_store() -> ModelTranscriptFileStore:
    """Where a run's calls are kept, beside the graph it published."""

    return ModelTranscriptFileStore(settings.model_transcript_root)


@lru_cache(maxsize=1)
def get_narrative_prompt():
    """Load the prompt that reads a decided run back as prose.

    A fourth prompt file, and the only one whose output nothing downstream
    reads. It is versioned with the other three anyway: the account is shown
    beside the verdicts, so a reader has to be able to tell which text they
    are looking at and what wrote it.
    """

    return load_prompt(RUN_NARRATIVE_PROMPT)


def get_narrator() -> RunNarrator:
    """Provide the narrator, wired to the same model access everything uses."""

    return RunNarrator(get_ai_client(), get_narrative_prompt())


@lru_cache
def get_verdict_prompt():
    """Load the versioned prompt once, here, because this is the only layer
    that may read a file for the component.

    The component holds the shape and never the file: a prompt that a
    subcomponent could open would be a subcomponent that reads the repository
    it is reasoning about.
    """

    return load_prompt(PRIMARY_VERDICT_PROMPT)


@lru_cache
def get_challenge_prompt():
    """Load the verifier's prompt, which is a second file and not a flag.

    Two arms sharing one template would be indistinguishable in the results,
    and the version string is part of both the cache key and what a published
    verification is attributed to.
    """

    return load_prompt(CRITICAL_REFRAMING_PROMPT)


@lru_cache
def get_blind_prompt():
    """Load the blind arm's prompt, which shows the evidence and not the answer.

    A third file rather than the challenge prompt with the verdict omitted.
    Two arms sharing a template are indistinguishable in the results, and a
    template that could render a verdict is one edit away from leaking it.
    """

    return load_prompt(BLIND_VERDICT_PROMPT)


@lru_cache
def get_validation_service() -> ArchitectureValidationService:
    """Provide the validation service, wired to the configured input.

    Cached so the readers are built once. Declared as a dependency so a test
    can substitute a reader over a committed recording.
    """

    return ArchitectureValidationService(
        architecture_reader=get_architecture_reader(),
        normalization=ObservationNormalizationService(),
        knowledge=DecisionKnowledgeService(
            get_artifact_reader(), get_decision_store()
        ),
        evidence=EvidenceRetrievalService(get_artifact_reader()),
        reasoning=ValidationReasoningService(
            get_ai_client(),
            get_verdict_prompt(),
            REASONING_TASKS,
            provider=ai_settings.ai_provider,
            allow_arbiter_only=ai_settings.ai_allow_arbiter_only,
        ),
        verification=IndependentVerificationService(
            get_ai_client(),
            get_challenge_prompt(),
            TASK_VERIFICATION,
            provider=ai_settings.ai_provider,
            blind_prompt=get_blind_prompt(),
        ),
        classification=ClassificationService(),
        review=ArchitectReviewService(
            get_review_queue(),
            DecisionKnowledgeService(get_artifact_reader(), get_decision_store()),
        ),
        publishing=GraphPublishingService(get_graph_file_store()),
    )


@lru_cache(maxsize=1)
def get_graph_file_store() -> ValidatedGraphFileStore:
    """Where a run publishes the document the next component reads.

    The only one of the three stores that is wired here. The relational record
    and the graph projection are left unconfigured on purpose: a run on a
    laptop with no databases should report that it wrote one store, not warn
    twice about two it was never asked to write. Passing them is one argument
    each when the databases are part of the deployment.
    """

    return ValidatedGraphFileStore(settings.validated_graph_root)


@lru_cache(maxsize=1)
def get_release_dates() -> ReleaseDateReader:
    """Reads a release tag's date out of the ingestion workspace.

    Wired here rather than injected into the component: reading git history is
    the same category of thing as reading source code, which the component
    also does not do, so the date arrives as a parameter of the run.
    """

    return ReleaseDateReader(settings.repositories_root, SOURCE_DIRECTORY_NAME)


def review_binding(
    repository_id: str | None = None, release_id: str | None = None
) -> tuple[str, str] | None:
    """Which repository and release the review queue is for.

    Read from the ingestion workspace rather than written down here. The ids
    belong to whatever has been ingested on this machine, and a literal in
    this file is a subject system compiled into the product - which works
    until the second repository arrives and then mislabels every row it
    writes.

    A caller may name either id; what they do not name is resolved from the
    most recently ingested revision that matches what they did. `None` when
    nothing has been ingested, which is the same answer as a queue with no
    database behind it: there is nothing to queue against yet.
    """

    try:
        record = WorkspaceIndex(settings.repositories_root).resolve(
            repository_id, release_id
        ) if repository_id else _newest_ingested(release_id)
    except WorkspaceUnavailable:
        return None

    return (record.repository_key, record.release_id) if record else None


def _newest_ingested(release_id: str | None):
    """The most recent ingest, optionally of one named release."""

    records = WorkspaceIndex(settings.repositories_root).records()

    return next(
        (
            record
            for record in records
            if release_id is None or release_id in (record.release_id, record.release_tag)
        ),
        None,
    )


@lru_cache
def get_review_queue(repository_id: str = "", release_id: str = ""):
    """The review queue, or `None` when there is nothing to bind it to.

    `None` means *not configured*, which the review stage reports as a note
    rather than a warning: a run on a laptop with nothing installed queues
    nothing and says the facts are in the published document regardless. A
    configured queue that refused is a fault and is named as one.

    The queue is still bound to one repository and one release, which is
    wiring rather than data on the item - so a caller that forgot cannot
    write an item against the wrong release. What changed is where the pair
    comes from: the workspace, not a constant.
    """

    binding = review_binding(repository_id or None, release_id or None)

    if binding is None:
        return None

    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.infrastructure.postgres.database import DATABASE_URL
        from app.infrastructure.postgres.repositories.c2_review_repository import (
            PostgresReviewQueueRepository,
        )

        engine = create_engine(DATABASE_URL, connect_args={"connect_timeout": 3})
        engine.connect().close()
    except Exception:  # noqa: BLE001 - an absent database is a normal state
        return None

    return PostgresReviewQueueRepository(sessionmaker(bind=engine), *binding)


@router.get(
    "/pipeline",
    response_model=PipelineResponse,
    summary="Describe the validation pipeline",
    response_description="Every stage in run order, with how far each is built.",
)
def describe_pipeline():
    """Return the pipeline's stages in run order.

    Served from the component's own description of itself, so a client never
    has to carry its own copy of the stage list. Safe to call before anything
    has been ingested: it describes the component, not a run.
    """

    stages = [stage.to_dict() for stage in PIPELINE]

    return PipelineResponse(
        stage_count=len(stages),
        implemented_count=sum(1 for stage in PIPELINE if stage.implemented),
        stages=[StageDescriptionResponse(**stage) for stage in stages],
    )


class ModeAvailabilityResponse(BaseModel):
    """What one decision mode would find, before it is chosen."""

    mode: str = Field(description="The mode this row is about.")
    ran: bool = Field(
        description=(
            "Whether the sources behind this mode could run at all. False "
            "means the mode is not configured - which is a different answer "
            "from running and finding nothing, and the two must never be "
            "presented the same way."
        )
    )
    records: int = Field(description="Decisions this mode would supply.")
    reason: str | None = Field(
        default=None,
        description="Why it would supply none, when it would supply none.",
    )
    by_source: dict[str, int] = Field(
        default_factory=dict,
        description="The same number broken down by the source that found it.",
        examples=[{"config_scan": 25}],
    )
    source_notes: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "What a source said for itself, for the sources that said "
            "anything. A zero beside a source is not self-explanatory: it can "
            "mean the repository holds no written decisions, or that it holds "
            "many and none of them states a checkable constraint."
        ),
        examples=[
            {
                "repo_adr": "138 decision document(s) found in this "
                "repository; none declares a machine-readable constraint"
            }
        ],
    )


class DecisionSourcesResponse(BaseModel):
    """Every mode's yield for one release, so nobody chooses blind."""

    repository_id: str
    release_id: str
    recommended: str | None = Field(
        description="The mode with the most to offer, or null if none has any."
    )
    modes: list[ModeAvailabilityResponse] = Field(description="One row per mode.")


@router.get(
    "/decision-sources",
    response_model=DecisionSourcesResponse,
    summary="What each decision source would supply",
    response_description=(
        "One row per mode, with what it would find and why it would find "
        "nothing. Nothing is run and nothing is written."
    ),
    responses={
        status.HTTP_409_CONFLICT: {
            "description": "The repository has not been ingested, or the "
            "recovered architecture for that release cannot be read, so there "
            "are no manifest paths to scan."
        }
    },
)
def describe_decision_sources(
    repository_id: str,
    release_id: str,
    service: ArchitectureValidationService = Depends(get_validation_service),
    reader=Depends(get_architecture_reader),
):
    """Report what each decision mode would supply for one release.

    Read before a run rather than discovered during one. A mode's yield is
    the number a user needs at the moment they choose, and a number only
    obtainable by starting a run is not available then - which is how someone
    picks an empty mode and reads the result as a clean validation.

    It runs the sources, because running them is the only way to be sure the
    number is the one the run will produce. They read a handful of files, call
    no model and write nothing.
    """

    try:
        architecture = reader.read(repository_id, release_id)
    except (
        ArtifactUnavailableError,
        DecisionSourceError,
        GraphContractError,
        InventoryContractError,
        SnapshotContractError,
        IncoherentArchitecture,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error

    try:
        available = service.decision_sources(
            SourceRequest(
                code_repository_id=repository_id,
                release_id=release_id,
                extracted_at=datetime.now(UTC),
                manifest_paths=architecture.manifest_paths,
            )
        )
    except (ArtifactUnavailableError, DecisionSourceError) as error:
        # The sources read the repository, so this route needs the checkout as
        # well as the recording. Answered rather than raised: a user asking
        # which mode to pick before ingesting anything has made a mistake with
        # an obvious fix, and the sentence that says so is the whole answer.
        #
        # A source that cannot read a file it found is the same kind of
        # answer. One unparseable document in a repository must not turn
        # "what could this be validated against?" into a crash: the question
        # is asked before anything runs, and the refusal belongs to the run.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error

    best = max(available.values(), key=lambda found: found.records)

    return DecisionSourcesResponse(
        repository_id=repository_id,
        release_id=release_id,
        recommended=best.mode if best.records else None,
        modes=[
            ModeAvailabilityResponse(**found.to_dict())
            for found in sorted(available.values(), key=lambda found: found.mode)
        ],
    )


class DecisionRecordResponse(BaseModel):
    """One rule a mode would supply, with where it was read from."""

    decision_id: str
    subject: str
    constraint: str = Field(
        description="What the rule requires, from a closed four-value vocabulary."
    )
    object: str = Field(description="The other end of the rule; '*' means every element.")
    valid_from: str
    valid_to: str | None = Field(
        default=None, description="Null means the rule is still in force."
    )
    source: str = Field(description="The adapter that produced it.")
    source_tier: str = Field(description="How strong the kind of evidence is.")
    source_strength: str
    extraction_method: str = Field(
        description="Whether a person declared it or it was reconstructed."
    )
    source_ref: str = Field(description="The file it was read from.")
    start_line: int | None = Field(
        default=None, description="The first line it was read from, when it has one."
    )
    end_line: int | None = None
    rationale: str | None = None


class DecisionRecordsResponse(BaseModel):
    """Every rule one mode would supply, so a count can be checked."""

    repository_id: str
    release_id: str
    mode: str
    records: list[DecisionRecordResponse]


@router.get(
    "/decision-records",
    response_model=DecisionRecordsResponse,
    summary="The rules one decision mode would supply",
    response_description=(
        "One row per rule, each naming the file and the lines it was read "
        "from. Nothing is run and nothing is written."
    ),
    responses={
        status.HTTP_409_CONFLICT: {
            "description": "The repository has not been ingested, or the "
            "recovered architecture for that release cannot be read."
        }
    },
)
def list_decision_records(
    repository_id: str,
    release_id: str,
    mode: str = DEFAULT_MODE,
    service: ArchitectureValidationService = Depends(get_validation_service),
    reader=Depends(get_architecture_reader),
):
    """List the rules behind a mode's count.

    The count on its own invites one question - *and what are they?* - and a
    rule reconstructed from configuration has to answer it, because its whole
    claim is that it was read from a line somebody can open. This route is
    that answer, and it is read-only for the same reason the picker is.
    """

    try:
        architecture = reader.read(repository_id, release_id)
    except (
        ArtifactUnavailableError,
        DecisionSourceError,
        GraphContractError,
        InventoryContractError,
        SnapshotContractError,
        IncoherentArchitecture,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error

    try:
        records = service.decision_records(
            SourceRequest(
                code_repository_id=repository_id,
                release_id=release_id,
                extracted_at=datetime.now(UTC),
                manifest_paths=architecture.manifest_paths,
            ),
            mode,
        )
    except ValueError as error:
        # An unknown mode names itself in the message, so it is the answer.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    except (ArtifactUnavailableError, DecisionSourceError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error

    return DecisionRecordsResponse(
        repository_id=repository_id,
        release_id=release_id,
        mode=mode,
        records=[
            DecisionRecordResponse(
                decision_id=record.decision_id,
                subject=record.subject,
                constraint=str(record.constraint),
                object=record.object,
                valid_from=record.valid_from,
                valid_to=record.valid_to,
                source=record.source,
                source_tier=str(record.source_tier),
                source_strength=str(record.source_strength),
                extraction_method=str(record.extraction_method),
                source_ref=record.source_ref,
                start_line=record.source_span.start_line if record.source_span else None,
                end_line=record.source_span.end_line if record.source_span else None,
                rationale=record.rationale,
            )
            for record in records
        ],
    )


def _resolve_release_date(
    request: "ValidationRunRequest",
) -> tuple[datetime | None, str | None]:
    """When the release was cut, and which field said so.

    The caller wins when they supplied one: they know something the repository
    does not, and overriding a tag is the reason the field exists. Otherwise
    the tag's own date, then the tagged commit's author date, read from the
    workspace.

    `None` for both when neither answered. Nothing is invented - a plausible
    wrong date orders the consumer's timeline wrongly and cannot be told apart
    from a right one. The committer date is never used at all: it is rewritten
    by every rebase and reads as today.
    """

    if request.released_at is not None:
        return request.released_at, ReleaseDateSource.CALLER

    reader = get_architecture_reader()
    if isinstance(reader, GraphStoreReader):
        # Recovery resolved this already, from the tag then the commit then
        # the moment it ran, and it says which of the three answered. Reading
        # git a second time here could only produce a second opinion about a
        # field a consumer gates on.
        recovered = reader.released_at(request.repository_id, request.release_id)
        if recovered is not None:
            return recovered

    found = get_release_dates().read(request.repository_id, request.release_id)
    if found is None:
        return None, None
    return found


@router.post(
    "",
    response_model=ValidationRunResponse,
    summary="Validate one release",
    response_description=(
        "The run, with one record per stage. A run whose status is incomplete "
        "is a partial run and says which stages have not been built."
    ),
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "A field is missing or unusable - most often a "
            "release identifier that cannot be ordered against other "
            "releases, which leaves no temporal claim to make about it."
        },
        status.HTTP_409_CONFLICT: {
            "description": "The input for that repository and release cannot "
            "be used: the repository has not been ingested, or there is no "
            "recovered architecture recorded, or the one on disk is a schema "
            "version this component does not read, or it has a relationship "
            "naming an element it does not contain."
        },
    },
)
def run_validation(
    request: ValidationRunRequest,
    service: ArchitectureValidationService = Depends(get_validation_service),
    transcripts: ModelTranscriptFileStore = Depends(get_transcript_store),
):
    """Validate one release and return what each stage did.

    The two ways this can fail are deliberately different. An unusable release
    identifier is rejected against the field that carried it, because no
    amount of recovery output will fix it. A missing recovered architecture is
    a conflict with the current state of the workspace, because recording that
    release resolves it.
    """

    released_at, released_at_source = _resolve_release_date(request)

    # The calls are collected around the run rather than inside it. The
    # component names a task and is handed an answer; which model answered,
    # how long it took and what the request text was are facts about the
    # adapter, and a component that could see them is a component that could
    # start reasoning about them.
    calls = get_call_log()
    try:
        with calls.capture() as recorded:
            run = service.run(
                request.repository_id,
                request.release_id,
                decision_mode=request.decision_mode,
                adr_repository_id=request.adr_repository_id,
                verify=request.verify,
                arm=request.arm,
                released_at=released_at,
                released_at_source=released_at_source,
            )
    except NoDecisionsAvailable as error:
        # Not a fault in the request and not a fault here: there is nothing to
        # validate against. Refused rather than run, because an empty decision
        # store makes every fact uncovered and publishes a graph that reads
        # exactly like a clean validation of a healthy system. The detail
        # carries what each mode would have found, so the block doubles as the
        # thing that says which one to pick.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error
    except (
        ArtifactUnavailableError,
        DecisionSourceError,
        GraphContractError,
        InventoryContractError,
        SnapshotContractError,
        IncoherentArchitecture,
    ) as error:
        # Four shapes of one situation: the repository was never ingested, or
        # the recovered architecture for this release is missing, is a version
        # this component does not read, or does not hold together. All four
        # are about the state of the input rather than a fault here, and all
        # four are fixed by producing a usable recording - so all four are a
        # conflict and carry the message that says which one it was.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error

    transcripts.write(_transcript(run, recorded))

    return ValidationRunResponse(
        run_id=run.run_id,
        repository_id=run.repository_id,
        release_id=run.release_id,
        status=run.status,
        model_calls=run.model_calls,
        validation_confidence=run.validation_confidence,
        published_ref=run.published_ref,
        style_resolved=run.style_resolved,
        style_source=run.style_source,
        verification_arm=run.verification_arm,
        verification_mode=run.verification_mode,
        decision_mode=run.decision_mode,
        stages=[StageRecordResponse(**stage.to_dict()) for stage in run.stages],
    )

class ReviewItemResponse(BaseModel):
    """One fact waiting on an architect."""

    item_id: str
    fact_id: str
    bucket: str
    confidence: float
    source_tier: str | None = Field(
        default=None,
        description=(
            "The tier of the source the decision came from, which is what "
            "lets a screen say *why* this needs a person rather than showing "
            "a number below a threshold."
        ),
    )
    evidence_refs: list[str] = Field(
        description="References, never the evidence. The item holds no copies."
    )
    candidate_decision_id: str | None = Field(
        default=None,
        description="What a confirmation would ratify, when there is one.",
    )
    status: str
    created_at: datetime


class ReviewDecisionRequest(BaseModel):
    """What an architect decided about one queued fact."""

    accepted: bool = Field(
        description=(
            "true ratifies the candidate decision, which raises its strength "
            "in the knowledge log so the next run can reach a verdict that is "
            "currently capped. false records that a mined candidate was wrong "
            "and appends nothing - a rejection is kept, because the ratio of "
            "confirmations to rejections is the only ground truth this system "
            "produces for free."
        )
    )
    decided_by: str = Field(
        default="architect",
        description=(
            "A role rather than a person: the role exists in the system and "
            "whoever fills it is interchangeable."
        ),
    )
    note: str | None = None


class ReviewOutcomeResponse(BaseModel):
    """What recording one decision did."""

    item_id: str
    status: str
    ratified: int = Field(
        description=(
            "How many decision versions the confirmation applied to. Zero on "
            "a rejection, and zero on an acceptance whose candidate has been "
            "superseded since it was queued - which is information for "
            "whoever pressed the button rather than a fault, and is why it is "
            "returned instead of logged."
        )
    )
    note: str = Field(
        description="What has not happened yet, in words, for the screen."
    )


@router.get(
    "/reviews",
    response_model=list[ReviewItemResponse],
    summary="List the facts waiting on an architect",
    response_description="Every undecided item, oldest first.",
)
def list_reviews(
    repository_id: str | None = None,
    release_id: str | None = None,
    service: ArchitectureValidationService = Depends(get_validation_service),
):
    """Return the queue, oldest first.

    `repository_id` and `release_id` select which queue, and both default to
    the most recently ingested revision. One subject system therefore needs
    neither, and a second one does not need a code change.

    Oldest first and not newest: a queue read newest-first buries the item
    that has been waiting longest, which is the one a reviewer most needs.

    An empty list is a real answer and not an error. On this subject system
    every service pair is covered by an enforced policy, so nothing falls to a
    weak tier and nothing needs a person - which is a property of the
    repository rather than of the component.
    """

    queue = get_review_queue(repository_id or "", release_id or "")
    if queue is None:
        return []
    return [ReviewItemResponse(**_review_item(item)) for item in queue.pending()]


@router.post(
    "/reviews/{item_id}",
    response_model=ReviewOutcomeResponse,
    summary="Record an architect's decision on one queued fact",
    response_description="What the decision did, and what it did not do.",
    responses={404: {"description": "No such review item."}},
)
def decide_review(
    item_id: str,
    request: ReviewDecisionRequest,
    repository_id: str | None = None,
    service: ArchitectureValidationService = Depends(get_validation_service),
):
    """Record the decision, and ratify the candidate when it is accepted.

    **This does not re-run the release.** It appends to the knowledge log and
    returns. When a verdict changes has to be a decision somebody made rather
    than a side effect: five confirmations would otherwise start five runs,
    each resolving against a log the others were still changing, and the
    verdicts would depend on the order the buttons were pressed.

    So the loop is confirm, then run - and the run is the ordinary
    `POST /validations`, not a special path.
    """

    decision = ReviewDecision(
        item_id=item_id,
        accepted=request.accepted,
        decided_by=request.decided_by,
        decided_at=datetime.now(UTC),
        note=request.note,
    )

    binding = review_binding(repository_id)

    if binding is None:
        # Nothing ingested, so there is no decision log to ratify into. A 404
        # would say the item does not exist, which is a different thing from
        # having nowhere to write the answer.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No ingested repository to record a decision against. Ingest "
                "the repository, or name one with ?repository_id=."
            ),
        )

    try:
        outcome = service.record_review(decision, binding[0])
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except QueueUnavailable as error:
        # The queue is where the decision has to be written down, so unlike a
        # run this cannot degrade: there is nowhere to record the answer.
        raise HTTPException(
            status_code=503,
            detail=f"the review queue is unavailable: {error}",
        ) from error

    return ReviewOutcomeResponse(
        item_id=outcome.item_id,
        status=str(outcome.status),
        ratified=outcome.ratified,
        note=(
            "the rule is now authoritative in the decision log. This fact "
            "still reads as it did, because verdicts are never rewritten - "
            "the next run will resolve it as a ratified rule and the ceiling "
            "will lift."
            if outcome.ratified
            else "recorded. Nothing was appended to the decision log."
        ),
    )


def _review_item(item) -> dict:
    return {
        "item_id": item.item_id,
        "fact_id": item.fact_id,
        "bucket": str(item.bucket),
        "confidence": item.confidence,
        "source_tier": str(item.source_tier) if item.source_tier else None,
        "evidence_refs": list(item.evidence_refs),
        "candidate_decision_id": item.candidate_decision_id,
        "status": str(item.status),
        "created_at": item.created_at,
    }


@router.get(
    "/graph",
    summary="The published graph for one release",
    response_description=(
        "The validated architecture as the node-link document the next "
        "component reads, exactly as it was published."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "That release has not been validated, which is a "
            "state rather than a fault: it has its own screen."
        }
    },
)
def read_published_graph(repository_id: str, release_id: str):
    """Return the document the most recent completed run published.

    Read from the file rather than rebuilt from the run record, so the screen
    and the next component are looking at the same bytes. A release nobody has
    validated is a 404 with a sentence, not an empty graph: an empty graph and
    a graph of a system with nothing in it are different claims.
    """

    document = get_graph_file_store().read(repository_id, release_id)

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No validated graph for '{release_id}'. Run a validation for "
                "that release first."
            ),
        )

    return document


def _transcript(run, calls: list) -> dict:
    """One run's calls, in the shape the store keeps and the screen reads.

    The summary is computed here rather than on the way out, so a transcript
    read back from disk carries the same counts it was written with. A figure
    recomputed at read time is a figure that can disagree with the file it
    came from.
    """

    return {
        "run_id": run.run_id,
        "repository_id": run.repository_id,
        "release_id": run.release_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "reasoner_model": run.reasoner_model,
        "verifier_model": run.verifier_model,
        "schema_mode": ai_settings.ai_schema_mode,
        "temperature": ai_settings.ai_temperature,
        "base_url": ai_settings.ai_base_url,
        "key_configured": bool(ai_settings.ai_api_key),
        "summary": summarise(calls),
        "calls": [call.to_dict() for call in calls],
    }


class ModelCallResponse(BaseModel):
    """One request to one model, as it was sent and answered."""

    sequence: int = Field(description="Position in the run, from one.")
    task: str = Field(
        description="What was being asked, never which model was wanted.",
        examples=["primary_verdict"],
    )
    requested_model: str = Field(description="The model configuration named.")
    answered_model: str = Field(
        description="The model the provider reported. A provider can serve a "
        "different build under the name it was asked for, so the two are kept "
        "apart rather than assumed equal."
    )
    prompt: str = Field(description="The request text, in full, as it was sent.")
    prompt_version: str = Field(description="The prompt file and its version.")
    schema_mode: str = Field(description="strict or best_effort.")
    evidence_hash: str = Field(description="The sealed evidence this answered about.")
    outcome: str = Field(
        description=(
            "answered - a model was reached on this run. replayed - the "
            "identical question was answered earlier and came from the cache, "
            "which is a model's answer and not the table's. unavailable - "
            "nothing answered. unusable - something answered and the answer "
            "could not be read."
        ),
        examples=["answered"],
    )
    latency_ms: int = Field(description="Wall-clock time for this call.")
    response: dict | None = Field(
        default=None, description="The parsed answer, or null if there is none."
    )
    error: str | None = Field(
        default=None, description="Why there is no answer, or null."
    )
    prompt_tokens: int = Field(description="Zero on a replay: nothing was sent.")
    completion_tokens: int = Field(description="Zero on a replay.")


class TranscriptResponse(BaseModel):
    """Every model call one run made.

    This answers a question the rest of the screen cannot: whether a model was
    involved at all. A run on a machine with no key reaches the same verdict
    on an easy fact as a run with one, because the deterministic table agrees
    with the model there - so every published field looks identical, and only
    the calls tell the two runs apart.
    """

    run_id: str
    repository_id: str
    release_id: str
    generated_at: str
    reasoner_model: str | None = None
    verifier_model: str | None = None
    schema_mode: str = Field(description="How the answers were constrained.")
    temperature: float
    base_url: str = Field(
        description="The endpoint the calls went to. No key is ever returned "
        "here, only whether one is set."
    )
    key_configured: bool = Field(
        description="Whether a key was configured when this ran. False with "
        "calls recorded is impossible; false with none is the keyless run."
    )
    summary: dict[str, int] = Field(
        description="Counts by outcome, plus the tokens the live calls spent."
    )
    calls: list[ModelCallResponse] = Field(description="In the order they were made.")


@router.get(
    "/transcript",
    response_model=TranscriptResponse,
    summary="What one run sent to each model, and what came back",
    response_description=(
        "Every call the run made, in order, with the request text and the "
        "parsed answer."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "No transcript was kept for that release. Either it "
            "has not been validated, or it was validated before transcripts "
            "were recorded - which is a state rather than a run that called "
            "nothing."
        }
    },
)
def read_transcript(
    repository_id: str,
    release_id: str,
    transcripts: ModelTranscriptFileStore = Depends(get_transcript_store),
):
    """Return the most recent run's calls for one release."""

    document = transcripts.read(repository_id, release_id)

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No model transcript for '{release_id}'. Run the validation "
                "again and the calls it makes will be recorded."
            ),
        )

    return document


class ModelProbeResponse(BaseModel):
    """One model, asked a trivial question on purpose."""

    task: str = Field(description="The task this model is configured to answer.")
    requested_model: str
    answered_model: str | None = Field(
        default=None, description="Null when nothing answered."
    )
    reachable: bool
    latency_ms: int
    strict_schema: bool = Field(
        description="Whether the answer was constrained by a JSON schema. A "
        "model that cannot be relied on for that is a different design here, "
        "not a slower one."
    )
    prompt: str = Field(description="Exactly what was sent.")
    response: dict | None = Field(default=None, description="Exactly what came back.")
    error: str | None = Field(default=None)


class ModelAccessResponse(BaseModel):
    """Whether the configured models answer right now.

    One live call per configured model, with the cache deliberately out of the
    way. The point is the word *now*: every other figure on this screen can be
    satisfied by an answer a model gave last week, and a reader asking whether
    this installation reaches a model at all is not asking about last week.
    """

    base_url: str
    key_configured: bool = Field(
        description="Whether a key is set. The key itself is never returned."
    )
    schema_mode: str
    temperature: float
    arbiter_only_allowed: bool = Field(
        description=(
            "Whether a verdict with no model behind it is permitted in this "
            "deployment. True is the demonstration's rollback, and it is why a "
            "keyless run still produces verdicts - which is the setting that "
            "makes a run with no model look like a run with one."
        )
    )
    reachable: int = Field(description="How many of the probed models answered.")
    probed: list[ModelProbeResponse]


PROBE_PROMPT = (
    "Evidence:\n"
    "  [ev:1] rule: service-a may call service-b\n"
    "  [ev:2] observed: service-a calls service-b\n\n"
    "Does the observation obey the rule? Cite only the references above."
)

PROBE_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "cited_evidence_refs": {"type": "array", "items": {"type": "string"}},
        "verdict": {"type": "string", "enum": ["confirms", "contradicts"]},
    },
}


@router.post(
    "/model-access",
    response_model=ModelAccessResponse,
    summary="Ask every configured model a trivial question, now",
    response_description=(
        "One probe per configured model, each carrying the request that was "
        "sent and the answer that came back."
    ),
)
def check_model_access():
    """Call each configured model once and report what happened.

    A POST rather than a GET because it spends tokens, and because a reader
    pressing a button is the only thing that should cause it.

    It reaches the provider adapter directly rather than going through the AI
    interface, and it is the one route allowed to: the interface caches, and a
    cached answer would let this report a reachable model on a machine with no
    network. What is being checked is the account and the endpoint, not the
    code path a verdict takes.
    """

    probed = [
        _probe(task)
        for task in (
            TASK_PRIMARY_VERDICT,
            TASK_PRIMARY_VERDICT_FALLBACK,
            TASK_VERIFICATION,
            TASK_NARRATION,
        )
    ]

    return ModelAccessResponse(
        base_url=ai_settings.ai_base_url,
        key_configured=bool(ai_settings.ai_api_key),
        schema_mode=ai_settings.ai_schema_mode,
        temperature=ai_settings.ai_temperature,
        arbiter_only_allowed=ai_settings.ai_allow_arbiter_only,
        reachable=len([probe for probe in probed if probe.reachable]),
        probed=probed,
    )


def _probe(task: str) -> ModelProbeResponse:
    """Send one trivial request to the model that answers `task`.

    A failure is reported rather than raised. Three models answering and one
    refusing is the useful answer, and an exception would replace it with the
    first failure and nothing else.
    """

    model_id = ai_settings.model_for(task)
    strict = ai_settings.ai_schema_mode == SCHEMA_MODE_STRICT
    provider = OpenAICompatibleProvider(
        base_url=ai_settings.base_url_for(task),
        api_key=ai_settings.ai_api_key,
        timeout_seconds=ai_settings.ai_timeout_seconds,
    )

    started = time.perf_counter()
    try:
        answer = provider.complete(
            model_id=model_id,
            prompt=PROBE_PROMPT,
            schema=PROBE_SCHEMA,
            strict=strict,
            temperature=ai_settings.ai_temperature,
            seed=ai_settings.ai_seed,
        )
    except ProviderError as error:
        return ModelProbeResponse(
            task=task,
            requested_model=model_id,
            reachable=False,
            latency_ms=int((time.perf_counter() - started) * 1000),
            strict_schema=strict,
            prompt=PROBE_PROMPT,
            error=str(error),
        )

    return ModelProbeResponse(
        task=task,
        requested_model=model_id,
        answered_model=answer["model_id"],
        reachable=True,
        latency_ms=int((time.perf_counter() - started) * 1000),
        strict_schema=strict,
        prompt=PROBE_PROMPT,
        response=answer["content"],
    )


class NarrativeResponse(BaseModel):
    """One run, written out as sentences by a model.

    **It is a reading of the result and not part of it.** Nothing here reaches
    a verdict, a confidence or the published graph, and where a sentence
    disagrees with a figure beside it the figure is the one to believe. The
    model that wrote it travels with it, so that stays checkable rather than
    remembered.
    """

    headline: str
    what_it_read: str
    what_it_concluded: str
    what_to_distrust: str
    model_id: str = Field(description="What wrote these paragraphs.")
    prompt_version: str
    cached: bool = Field(
        description="Whether this account was written on this request or "
        "replayed from an identical one."
    )
    figures: dict = Field(
        description="Exactly the figures the model was shown. Returned so a "
        "reader can check a sentence against the numbers behind it rather "
        "than against the rest of the screen."
    )


@router.post(
    "/narrative",
    response_model=NarrativeResponse,
    summary="Read a finished run back as prose",
    response_description=(
        "Four paragraphs written by a model from the published figures, with "
        "the figures it was shown."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "That release has not been validated, so there is "
            "no result to describe."
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "No model could be reached to write the account. "
            "Reported as an absence rather than filled in from a template, "
            "because text assembled here would read like the model's."
        },
    },
)
def narrate_run(
    repository_id: str,
    release_id: str,
    narrator: RunNarrator = Depends(get_narrator),
    transcripts: ModelTranscriptFileStore = Depends(get_transcript_store),
):
    """Describe one release's validation in plain English."""

    document = get_graph_file_store().read(repository_id, release_id)

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No validated graph for '{release_id}'. There is no result "
                "to describe until that release has been validated."
            ),
        )

    transcript = transcripts.read(repository_id, release_id) or {}
    brief = _brief(document, transcript)

    try:
        narration = narrator.narrate(brief, transcript.get("calls", []))
    except NarrationUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error

    return NarrativeResponse(**narration.to_dict(), figures=brief)


def _brief(document: dict, transcript: dict) -> dict:
    """The published figures, and nothing else, as the narrator receives them.

    Built from the document rather than from the run record on purpose. The
    document is what a reader is looking at, so an account written from
    anything else could be accurate about a run and still disagree with the
    screen it sits on.
    """

    graph = document.get("graph", {})
    stamp = graph.get("run", {})
    edges = document.get("links", [])

    judged = [edge for edge in edges if edge.get("produced_by") == "model"]

    return {
        "run_id": stamp.get("run_id", ""),
        "repository_id": graph.get("repository_id", ""),
        "release_id": graph.get("release_id", ""),
        "architecture_style": graph.get("architecture_style", ""),
        "architecture_style_source": graph.get("architecture_style_source", ""),
        "validation_confidence": graph.get("validation_confidence", 0.0),
        "elements": len(document.get("nodes", [])),
        "dependencies": len(edges),
        "reasoner_model": stamp.get("reasoner_model"),
        "verifier_model": stamp.get("verifier_model"),
        "prompt_versions": ", ".join(stamp.get("prompt_versions") or []),
        "verdict_buckets": _tally(edges, "bucket"),
        "who_produced_the_verdict": _tally(edges, "produced_by"),
        "what_the_second_model_said": _tally(judged, "verification_outcome"),
        "what_the_table_said": _tally(judged, "arbiter_agreement"),
        "model_calls_on_the_last_run": transcript.get("summary", {}),
        "key_configured": transcript.get("key_configured"),
    }


def _tally(edges: list[dict], field_name: str) -> dict:
    """Count one field's values across the edges, naming the absent ones.

    An absent value is counted under "none" rather than dropped. A check that
    did not happen has to appear in a count the model is shown, or the account
    describes a run in which everything was checked.
    """

    counts: dict[str, int] = {}
    for edge in edges:
        value = edge.get(field_name) or "none"
        counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items()))
