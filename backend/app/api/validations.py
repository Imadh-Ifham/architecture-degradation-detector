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

from datetime import UTC, datetime
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.components.architecture_validation import (
    PIPELINE,
    ArchitectureValidationService,
)
from app.components.architecture_validation.architect_review import (
    ArchitectReviewService,
)
from app.components.architecture_recovery.repository_ingestion.service import (
    SOURCE_DIRECTORY_NAME,
)
from app.components.architecture_validation.classification import ClassificationService
from app.components.architecture_validation.decision_knowledge import (
    DEFAULT_MODE,
    DecisionKnowledgeService,
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
from app.infrastructure.decision_log import JsonlDecisionStore
from app.infrastructure.git.workspace_artifact_reader import WorkspaceArtifactReader
from app.infrastructure.recovery_gateway import (
    InventoryContractError,
    InventoryFileArchitectureReader,
    SnapshotContractError,
    SnapshotFileReader,
)


router = APIRouter(prefix="/validations", tags=["Validation"])


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
    release_id: str = Field(
        min_length=1,
        description=(
            "A version tag, with or without a leading v. It has to order "
            "against other releases - a date stamp or a build label is "
            "refused, because the decision history compares releases to each "
            "other rather than to a calendar."
        ),
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

    if settings.architecture_source == "snapshot":
        return SnapshotFileReader(settings.snapshot_root)
    if settings.architecture_source == "inventory":
        return InventoryFileArchitectureReader(settings.repositories_root)

    raise ValueError(
        f"architecture_source is '{settings.architecture_source}'; "
        "expected 'snapshot' or 'inventory'."
    )


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
        reasoning=ValidationReasoningService(),
        verification=IndependentVerificationService(),
        classification=ClassificationService(),
        review=ArchitectReviewService(),
        publishing=GraphPublishingService(),
    )


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
            "description": "The recovered architecture for that release "
            "cannot be read, so there are no manifest paths to scan."
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
        InventoryContractError,
        SnapshotContractError,
        IncoherentArchitecture,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error

    available = service.decision_sources(
        SourceRequest(
            code_repository_id=repository_id,
            release_id=release_id,
            extracted_at=datetime.now(UTC),
            manifest_paths=architecture.manifest_paths,
        )
    )
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
            "description": "The recovered architecture for that repository and "
            "release cannot be used: there is none recorded, or the one on "
            "disk is a schema version this component does not read, or it has "
            "a relationship naming an element it does not contain."
        },
    },
)
def run_validation(
    request: ValidationRunRequest,
    service: ArchitectureValidationService = Depends(get_validation_service),
):
    """Validate one release and return what each stage did.

    The two ways this can fail are deliberately different. An unusable release
    identifier is rejected against the field that carried it, because no
    amount of recovery output will fix it. A missing recovered architecture is
    a conflict with the current state of the workspace, because recording that
    release resolves it.
    """

    try:
        run = service.run(
            request.repository_id,
            request.release_id,
            decision_mode=request.decision_mode,
            adr_repository_id=request.adr_repository_id,
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
        InventoryContractError,
        SnapshotContractError,
        IncoherentArchitecture,
    ) as error:
        # Three shapes of the same situation: the recovered architecture for
        # this release is missing, is a version this component does not read,
        # or does not hold together. All three are about the state of the
        # input rather than a fault here, and all three are fixed by producing
        # a usable recording - so all three are a conflict and carry the
        # message that says which one it was.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error

    return ValidationRunResponse(
        run_id=run.run_id,
        repository_id=run.repository_id,
        release_id=run.release_id,
        status=run.status,
        model_calls=run.model_calls,
        published_ref=run.published_ref,
        style_resolved=run.style_resolved,
        style_source=run.style_source,
        decision_mode=run.decision_mode,
        stages=[StageRecordResponse(**stage.to_dict()) for stage in run.stages],
    )
