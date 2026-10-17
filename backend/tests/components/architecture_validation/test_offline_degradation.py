"""The offline path, through the real adapter rather than a scripted one.

Author: Aman Mohamed M.A
Date: 2026-10-18
Description:
    What the component does with no key and nothing to reach.

    Every other test of the ladder scripts a provider that fails on demand,
    which proves the ladder reacts correctly to the port's errors. It cannot
    prove that the real adapter *produces* those errors: a dead endpoint that
    raised something the component does not catch would pass every scripted
    test and abort the demonstration.

    So these tests build the real HTTP adapter, point it at a closed port and
    give it no key. Loopback to a closed port is refused immediately, so there
    is no network dependency and no waiting - which is why this runs in the
    default suite rather than behind the `live` marker.

    Two rungs are covered. Rung 4, the local runtime, which answers nothing
    when no endpoint is configured for it. And rung 5, the arbiter alone,
    which is the demonstration's rollback: the verdicts below are what a
    panel would see if the venue network were unusable.
"""

from pathlib import Path

import pytest

from app.api.validations import REASONING_TASKS
from app.components.architecture_validation.decision_knowledge import (
    DecisionKnowledgeService,
)
from app.components.architecture_validation.evidence_retrieval import (
    EvidenceRetrievalService,
)
from app.components.architecture_validation.models import Verdict, VerdictSource
from app.components.architecture_validation.observation_normalization import (
    ObservationNormalizationService,
)
from app.components.architecture_validation.validation_reasoning import (
    ArbiterOnlyRefused,
    ValidationReasoningService,
)
from app.components.architecture_validation.validation_reasoning._arbiter import decide
from app.infrastructure.ai import AISettings, ConfiguredAIClient, VerdictCache
from app.infrastructure.ai.prompt_library import load_prompt
from app.infrastructure.ai.providers.openai_compatible import OpenAICompatibleProvider
from app.infrastructure.decision_log import JsonlDecisionStore
from app.infrastructure.recovery_gateway import SnapshotFileReader

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "validation"
SUBJECT = FIXTURES / "subject"
SNAPSHOTS = Path(__file__).resolve().parents[3] / "data" / "snapshots"

REPOSITORY = "online-boutique"
RELEASE = "v0.10.0"

NOWHERE = "http://127.0.0.1:9/v1"
"""Port 9 is the discard port and nothing listens on it here.

A closed loopback port rather than an unroutable address, because a refused
connection returns at once and a black-holed one waits for the timeout.
"""


class WorkspaceReader:
    """Reads the committed subject fixture tree for one release."""

    def read_text(self, repository_id, release_id, path):
        return (SUBJECT / release_id / path).read_text(encoding="utf-8")

    def list_paths(self, repository_id, release_id, pattern):
        root = SUBJECT / release_id
        return sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.glob(pattern))


def unreachable(allow_arbiter_only: bool = True) -> ValidationReasoningService:
    """The real wiring, with the real adapter aimed at a closed port.

    No key, and that is part of the case: a run on a machine that was never
    given one must behave the same as a run whose network died.
    """

    settings = AISettings(
        ai_api_key="",
        ai_base_url=NOWHERE,
        ai_local_base_url="",
        ai_cache_enabled=False,
        ai_timeout_seconds=2.0,
    )
    return ValidationReasoningService(
        ConfiguredAIClient(
            OpenAICompatibleProvider(
                base_url=settings.ai_base_url,
                api_key=settings.ai_api_key,
                timeout_seconds=settings.ai_timeout_seconds,
            ),
            settings=settings,
            cache=VerdictCache(settings.ai_cache_directory, enabled=False),
        ),
        load_prompt("primary_verdict.v1.md"),
        REASONING_TASKS,
        provider=settings.ai_provider,
        allow_arbiter_only=allow_arbiter_only,
    )


def governed(limit: int):
    """The first `limit` facts of the release that resolved to a rule."""

    architecture = SnapshotFileReader(SNAPSHOTS).read(REPOSITORY, RELEASE)
    knowledge = DecisionKnowledgeService(
        WorkspaceReader(), JsonlDecisionStore(FIXTURES / "decisions")
    )
    evidence = EvidenceRetrievalService(WorkspaceReader())

    taken = 0
    for observed in ObservationNormalizationService().normalise(architecture).facts:
        resolution = knowledge.resolve(observed, REPOSITORY)
        if resolution.governing is None:
            continue
        yield observed, resolution, evidence.assemble(observed, resolution, architecture)
        taken += 1
        if taken == limit:
            return


@pytest.fixture(scope="module")
def offline_verdicts():
    """Three real facts judged with nothing reachable, computed once."""

    reasoner = unreachable()
    return [
        reasoner.judge(package, decide(observed, resolution.governing))
        for observed, resolution, package in governed(3)
    ]


class TestTheRollback:
    """What the screen shows when no model can be reached."""

    def test_every_governed_fact_still_gets_a_verdict(self, offline_verdicts):
        assert len(offline_verdicts) == 3
        assert all(
            verdict.verdict is not Verdict.INSUFFICIENT_EVIDENCE
            for verdict in offline_verdicts
        )

    def test_not_one_of_them_pretends_a_model_was_involved(self, offline_verdicts):
        """Four separate fields say it, because this is the failure the whole
        unit is organised against: an unchecked fact reading as a checked one."""

        for verdict in offline_verdicts:
            assert verdict.produced_by is VerdictSource.ARBITER
            assert verdict.model_id == "none"
            assert verdict.ladder_rung == 5
            assert verdict.reasoning.startswith("No model was available")

    def test_there_is_no_agreement_to_report_rather_than_a_passed_check(
        self, offline_verdicts
    ):
        assert all(verdict.arbiter_agreement is None for verdict in offline_verdicts)

    def test_each_one_still_cites_a_reference_that_exists(self, offline_verdicts):
        """The citation contract is not relaxed because no model was involved."""

        assert all(verdict.cited_evidence_refs for verdict in offline_verdicts)

    def test_a_run_that_reports_numbers_fails_instead_of_degrading(self):
        """The same conditions, with the switch off, stop the run.

        A measurement taken on the ladder's bottom rung would describe the
        deterministic table and be read as describing a model.
        """

        observed, resolution, package = next(governed(1))
        subject = unreachable(allow_arbiter_only=False)

        with pytest.raises(ArbiterOnlyRefused) as refused:
            subject.judge(package, decide(observed, resolution.governing))

        assert refused.value.fact_id == package.fact_id
        assert len(refused.value.attempted) == len(REASONING_TASKS)
