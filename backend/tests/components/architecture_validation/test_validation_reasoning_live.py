"""The reasoning stage against a real model, over the committed corpus.

Author: Aman Mohamed M.A
Date: 2026-10-18
Description:
    Twenty real calls, and two numbers out of them: how often a strict schema
    held, and how often every citation resolved to evidence that was actually
    supplied. Both bars are set in this file above the test that measures
    them, because a threshold chosen after seeing the result is not a
    threshold.

    This is one test with one report rather than twenty tests, since the
    deliverable is the rate and not a pass per fact. It runs the real
    subcomponent over real packages: the decisions recovered from the
    committed subject tree, the evidence assembled by the retrieval stage, the
    versioned prompt file, the four guards, and the arbiter comparison. The
    only thing that is not production wiring is the artifact reader, which
    reads the committed fixture tree instead of a clone.

    Deselected by default. `pyproject.toml` sets `-m 'not live'`, so the suite
    stays runnable with no key and no network.

        uv run pytest -m live -k reasoning_live -v -s

    The cache is off for the whole run. A cached answer would make the second
    run report the first run's luck, and the rate is the only thing being
    measured.
"""

import time
from pathlib import Path

import pytest

from app.components.architecture_validation.decision_knowledge import (
    DecisionKnowledgeService,
)
from app.components.architecture_validation.evidence_retrieval import (
    EvidenceRetrievalService,
)
from app.components.architecture_validation.models import GuardFailure, VerdictSource
from app.components.architecture_validation.observation_normalization import (
    ObservationNormalizationService,
)
from app.components.architecture_validation.validation_reasoning import (
    ValidationReasoningService,
)
from app.components.architecture_validation.validation_reasoning._arbiter import decide
from app.components.architecture_validation.validation_reasoning._prompt import (
    verdict_schema,
)
from app.infrastructure.ai import (
    TASK_PRIMARY_VERDICT,
    TASK_PRIMARY_VERDICT_FALLBACK,
    TASK_PRIMARY_VERDICT_LOCAL,
    AISettings,
    ConfiguredAIClient,
    VerdictCache,
)
from app.infrastructure.ai.prompt_library import load_prompt
from app.infrastructure.ai.providers.openai_compatible import OpenAICompatibleProvider
from app.infrastructure.decision_log import JsonlDecisionStore
from app.infrastructure.recovery_gateway import SnapshotFileReader

pytestmark = pytest.mark.live

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "validation"
SUBJECT = FIXTURES / "subject"
SNAPSHOTS = Path(__file__).resolve().parents[3] / "data" / "snapshots"
REPOSITORY = "online-boutique"
PROMPT = "primary_verdict.v1.md"

TASKS = (
    TASK_PRIMARY_VERDICT,
    TASK_PRIMARY_VERDICT_FALLBACK,
    TASK_PRIMARY_VERDICT_LOCAL,
)
"""The ladder, in the order it is climbed - the same order the composition
root wires, because a spike that climbed a different ladder would measure a
configuration nothing else runs."""

SAMPLE = (("v0.10.0", 15), ("v0.9.0", 5))
"""Both releases, and the facts in the order the corpus yields them.

Taken in order rather than chosen, so the sample is not a selection of the
cases the model happens to do well on. Fifteen and five because the later
release is the one the demonstration runs and the earlier one is where the
superseded decision lives.
"""

SCHEMA_BAR = 20
CITATION_BAR = 19
"""The bars, fixed before the first run.

Twenty of twenty on schema, because strict mode is a decoding guarantee and
anything less than all of them means the guarantee is not what it claims.
Nineteen of twenty on citations, because a single invented citation is the
failure the retry rung exists for, and a run that needed it is still a run
the design handles.
"""

PACING_SECONDS = 7.0
"""Seconds between calls, so the run measures the model and not the quota.

The account allows 8 000 tokens a minute and a rendered package costs roughly
800, so about eight calls a minute fit. Flat out, twenty calls would exhaust
the minute's tokens around the tenth and the rest would arrive as rate-limit
failures - which the ladder would absorb by dropping to another model, and the
measurement would then be of two models and a quota rather than of one model.
"""


class WorkspaceReader:
    """Reads the committed subject fixture tree for one release."""

    def read_text(self, repository_id, release_id, path):
        return (SUBJECT / release_id / path).read_text(encoding="utf-8")

    def list_paths(self, repository_id, release_id, pattern):
        root = SUBJECT / release_id
        return sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.glob(pattern))


def governed(release):
    """Every fact of one release that resolved to a governing decision.

    The model is only ever asked about these. An uncovered or ambiguous fact
    has no rule to be checked against and reaches its bucket without a call.
    """

    architecture = SnapshotFileReader(SNAPSHOTS).read(REPOSITORY, release)
    knowledge = DecisionKnowledgeService(
        WorkspaceReader(), JsonlDecisionStore(FIXTURES / "decisions")
    )
    evidence = EvidenceRetrievalService(WorkspaceReader())

    for observed in ObservationNormalizationService().normalise(architecture).facts:
        resolution = knowledge.resolve(observed, REPOSITORY)
        if resolution.governing is None:
            continue
        yield observed, resolution, evidence.assemble(observed, resolution, architecture)


def sample():
    for release, take in SAMPLE:
        for index, entry in enumerate(governed(release)):
            if index >= take:
                break
            yield release, entry


@pytest.fixture
def settings() -> AISettings:
    configured = AISettings(ai_cache_enabled=False)
    if not configured.ai_api_key:
        pytest.skip("no ai_api_key in .env - put the key there and re-run")
    return configured


@pytest.fixture
def client(settings: AISettings) -> ConfiguredAIClient:
    return ConfiguredAIClient(
        OpenAICompatibleProvider(
            base_url=settings.ai_base_url,
            api_key=settings.ai_api_key,
            timeout_seconds=settings.ai_timeout_seconds,
        ),
        settings=settings,
        cache=VerdictCache(settings.ai_cache_directory, enabled=False),
    )


@pytest.fixture
def reasoner(client, settings) -> ValidationReasoningService:
    return ValidationReasoningService(
        client, load_prompt(PROMPT), TASKS, provider=settings.ai_provider
    )


def test_twenty_real_calls_hold_the_schema_and_resolve_their_citations(
    reasoner, capsys
):
    """The spike. One report, two assertions.

    Takes about two and a half minutes: twenty calls, paced so the account's
    token allowance is not the thing being measured.
    """

    rows = []
    for position, (release, (observed, resolution, package)) in enumerate(sample()):
        if position:
            time.sleep(PACING_SECONDS)

        started = time.perf_counter()
        verdict = reasoner.judge(package, decide(observed, resolution.governing))
        elapsed = time.perf_counter() - started

        # Computed here rather than read off the recorded guard failure. The
        # grounding claim is that a citation resolves to supplied evidence, and
        # a test that believed the flag would be asserting that the guard
        # recorded itself rather than that the model stayed inside its packet.
        invented = set(verdict.cited_evidence_refs) - set(package.refs)

        rows.append(
            {
                "release": release,
                "pair": f"{observed.subject.name} -> {observed.object.name}",
                "verdict": str(verdict.verdict),
                "source": verdict.produced_by,
                "model": verdict.model_id,
                "schema_held": GuardFailure.MALFORMED not in verdict.guard_failures,
                "resolved": not invented,
                "invented": sorted(invented),
                "guards": [str(failure) for failure in verdict.guard_failures],
                "retried": verdict.retried,
                "agreement": str(verdict.arbiter_agreement or "none"),
                "seconds": elapsed,
            }
        )

    schema_held = [row for row in rows if row["schema_held"]]
    resolved = [row for row in rows if row["resolved"]]
    from_model = [row for row in rows if row["source"] is VerdictSource.MODEL]
    retried = [row for row in rows if row["retried"]]
    seconds = sorted(row["seconds"] for row in rows)

    with capsys.disabled():
        print(f"\n  sample                 {len(rows)} facts, cache off")
        print(f"  schema held            {len(schema_held)} / {len(rows)}   (bar {SCHEMA_BAR})")
        print(f"  citations resolved     {len(resolved)} / {len(rows)}   (bar {CITATION_BAR})")
        print(f"  answered by the model  {len(from_model)} / {len(rows)}")
        print(f"  needed the retry       {len(retried)}")
        agreed = sum(1 for row in rows if row["agreement"] == "agreed")
        print(f"  agreed with the table  {agreed} / {len(rows)}")
        print(
            f"  seconds per call       min {seconds[0]:.2f}  "
            f"median {seconds[len(seconds) // 2]:.2f}  max {seconds[-1]:.2f}"
        )
        print()
        for row in rows:
            flags = "".join(
                (
                    " " if row["schema_held"] else "S",
                    " " if row["resolved"] else "C",
                    "r" if row["retried"] else " ",
                )
            )
            print(
                f"  {flags} {row['release']:>8} {row['pair']:<48} "
                f"{row['verdict']:<22} {row['agreement']:<14} {row['seconds']:.2f}s"
            )
            if row["guards"]:
                print(f"        guards: {', '.join(row['guards'])}")
            if row["invented"]:
                print(f"        invented: {', '.join(row['invented'])}")
        print()

    assert len(schema_held) == SCHEMA_BAR, [row["guards"] for row in rows]
    assert len(resolved) >= CITATION_BAR, [row["invented"] for row in rows if row["invented"]]


def test_the_field_order_the_model_actually_returns_is_recorded(client, capsys):
    """Recorded, not asserted, which is what the bar says.

    The schema declares `reasoning` before `verdict` so that the model works
    through the evidence and then concludes, instead of naming a conclusion and
    justifying it afterwards. Whether a given model honours declaration order
    is the model's business; what matters is that the verdict is not first, and
    a run that printed the order is a run that can be argued about.

    It goes through the client rather than the subcomponent because the
    subcomponent returns a verdict object, and an object has no field order to
    inspect.
    """

    _, (observed, resolution, package) = next(iter(sample()))
    result = client.complete(
        task=TASK_PRIMARY_VERDICT,
        prompt=f"Observed dependency: {observed.subject.name} depends on "
        f"{observed.object.name}. Decision in force: "
        f"{resolution.governing.decision_id}. Evidence refs: "
        f"{', '.join(sorted(package.refs))}. Cite only those refs.",
        schema=verdict_schema(),
        prompt_version="field-order",
        evidence_hash=package.evidence_hash,
    )

    order = list(result.content)
    with capsys.disabled():
        print(f"\n  {result.model_id} returned: {' -> '.join(order)}")
        print(f"  verdict is last: {order[-1] == 'verdict'}\n")
