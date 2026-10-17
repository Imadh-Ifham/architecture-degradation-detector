"""Validation reasoning service.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Judges one fact against the decision that governs it.

    Research module: M4.
"""

from ..models import (
    AIResult,
    ArbiterAgreement,
    ArbiterCheck,
    EvidencePackage,
    EvidenceRole,
    PrimaryVerdict,
    PromptTemplate,
    Verdict,
    VerdictSource,
)
from ._guards import check
from ._ladder import RUNG_ARBITER, RUNG_NOTHING, LadderOutcome, climb
from ._prompt import render, verdict_schema

NO_MODEL = "none"

CONCLUSIVE_VERDICTS = (Verdict.CONFIRMS, Verdict.CONTRADICTS)
"""The two the arbiter's table also speaks, and so the two it can be compared to."""


class ArbiterOnlyRefused(RuntimeError):
    """Rung 5 was reached in a run that was configured not to allow it.

    Raised rather than returned, because the thing being prevented is a run
    that *looks* complete. A keyless run degrades every governed fact to the
    table, each verdict honestly saying so, and a reported figure drawn from
    those would describe the table and be presented as describing a model.
    Failing the run is the only outcome a reader cannot misread.
    """

    def __init__(self, fact_id: str, attempted: tuple[str, ...]) -> None:
        super().__init__(
            f"No model could be reached for fact '{fact_id}' (tried: "
            f"{', '.join(attempted) or 'nothing'}), and this run does not "
            f"allow a verdict from the deterministic table alone. Set a key, "
            f"or set ai_allow_arbiter_only to permit it."
        )
        self.fact_id = fact_id
        self.attempted = attempted


class ValidationReasoningService:
    """Judges one fact against the decision that governs it."""

    def __init__(
        self,
        ai,
        prompt: PromptTemplate,
        tasks: tuple[str, ...],
        provider: str = "",
        allow_arbiter_only: bool = True,
    ) -> None:
        """Takes the model port, the loaded prompt and the ladder's task order.

        Three of them are required, so a service missing one cannot be built
        at all. The alternative - defaults, and a check inside `judge` - would
        put the failure one stage into a run instead of at start-up, which is
        the wrong end of the day to discover that nothing was wired.

        The prompt arrives as data and the rungs arrive as task names. Nothing
        here opens a file or chooses a model: the first is why `PromptTemplate`
        is passed in, and the second is why the fallbacks are tasks that
        configuration resolves.

        `allow_arbiter_only` defaults to true because the no-model rung is the
        demonstration's rollback and must work by default. It is turned off
        for a run whose numbers get reported, where a silent degradation to
        the table is the failure that matters. It arrives here as an argument
        for the same reason the prompt and the tasks do: this service reads no
        settings file.
        """

        self._ai = ai
        self._prompt = prompt
        self._tasks = tasks
        self._provider = provider
        self._allow_arbiter_only = allow_arbiter_only

    def judge(self, package: EvidencePackage, arbiter: ArbiterCheck) -> PrimaryVerdict:
        """Produces the primary verdict for one evidence package.

        Asks the AI interface for a task and a schema, never for a model. The
        schema is requested in strict mode, so an out-of-vocabulary verdict is
        structurally impossible rather than something this code has to catch.

        Four guards then run in ordinary Python. The most important of them
        checks that every cited reference exists in the package it came from -
        which no schema can express, and which is this component's only real
        guarantee that a conclusion is grounded.

        `arbiter` is computed by the caller and used **after** the answer comes
        back, never before it. A model told what the table decided agrees with
        it: the agreement rate goes to a hundred per cent, every measured
        number improves, and the only uncorrelated check in the component
        quietly disappears.
        """

        outcome = climb(
            self._ai,
            self._tasks,
            prompt=render(self._prompt, package),
            schema=verdict_schema(),
            prompt_version=self._prompt.version,
            evidence_hash=package.evidence_hash,
            accept=lambda content: check(content, package),
        )

        if outcome.result is not None:
            return self._from_model(package, arbiter, outcome, outcome.result)
        if outcome.rung == RUNG_ARBITER and arbiter.verdict is not None:
            if not self._allow_arbiter_only:
                raise ArbiterOnlyRefused(package.fact_id, outcome.attempted)
            return self._from_arbiter(package, arbiter, outcome)
        return self._from_nothing(package, arbiter, outcome)

    def _from_model(
        self,
        package: EvidencePackage,
        arbiter: ArbiterCheck,
        outcome: LadderOutcome,
        result: AIResult,
    ) -> PrimaryVerdict:
        """The normal path: a model answered and every guard let it through."""

        verdict = Verdict(result.content["verdict"])

        return PrimaryVerdict(
            fact_id=package.fact_id,
            verdict=verdict,
            reasoning=result.content["reasoning"],
            cited_evidence_refs=tuple(result.content["cited_evidence_refs"]),
            model_id=result.model_id,
            prompt_version=result.prompt_version,
            evidence_hash=package.evidence_hash,
            cached=result.cached,
            retried=outcome.retried,
            provider=self._provider,
            schema_mode=result.schema_mode,
            produced_by=VerdictSource.MODEL,
            arbiter=arbiter,
            arbiter_agreement=compare(verdict, arbiter),
            guard_failures=outcome.guard_failures,
            ladder_rung=outcome.rung,
        )

    def _from_arbiter(
        self,
        package: EvidencePackage,
        arbiter: ArbiterCheck,
        outcome: LadderOutcome,
    ) -> PrimaryVerdict:
        """Rung 5: nothing answered, so the table is the whole verdict.

        A real verdict with no model behind it, and every field that could
        hide that says so: `produced_by`, a model id of "none", and a
        reasoning sentence that opens by stating it. `arbiter_agreement` is
        null rather than `not_checked`, because the table did not abstain -
        there is simply no model verdict to compare it with.

        It cites the governing rule, which the package always carries first.
        The citation contract holds for this verdict exactly as it does for a
        model's: what it rests on is in the package and can be opened.
        """

        return PrimaryVerdict(
            fact_id=package.fact_id,
            verdict=arbiter.verdict,
            reasoning=(
                f"No model was available, so this verdict is the deterministic "
                f"table's alone: {arbiter.basis}. It was reached without "
                f"reading the reasoning a model would have supplied."
            ),
            cited_evidence_refs=_rule_refs(package),
            model_id=NO_MODEL,
            prompt_version=self._prompt.version,
            evidence_hash=package.evidence_hash,
            cached=False,
            retried=outcome.retried,
            provider=self._provider,
            schema_mode="",
            produced_by=VerdictSource.ARBITER,
            arbiter=arbiter,
            arbiter_agreement=None,
            guard_failures=outcome.guard_failures,
            ladder_rung=RUNG_ARBITER,
        )

    def _from_nothing(
        self,
        package: EvidencePackage,
        arbiter: ArbiterCheck,
        outcome: LadderOutcome,
    ) -> PrimaryVerdict:
        """Rung 6: no usable answer, and nothing substituted for one.

        Reached two ways, and the difference is in `guard_failures`. A model
        answered twice and both answers were rejected - and a rejected answer
        is **not** replaced by the table, because that would hide a bad model
        behind a good verdict. Or nothing answered and the table abstained too,
        which is the one case where this component has nothing to say.

        It cites nothing, which is the honest list: no claim was established,
        so there is nothing for a citation to support.
        """

        return PrimaryVerdict(
            fact_id=package.fact_id,
            verdict=Verdict.INSUFFICIENT_EVIDENCE,
            reasoning=_why_nothing(outcome, arbiter),
            cited_evidence_refs=(),
            model_id=outcome.result.model_id if outcome.result else NO_MODEL,
            prompt_version=self._prompt.version,
            evidence_hash=package.evidence_hash,
            cached=False,
            retried=outcome.retried,
            provider=self._provider,
            schema_mode="",
            produced_by=(
                VerdictSource.MODEL
                if outcome.guard_failures
                else VerdictSource.ARBITER
            ),
            arbiter=arbiter,
            arbiter_agreement=compare(Verdict.INSUFFICIENT_EVIDENCE, arbiter),
            guard_failures=outcome.guard_failures,
            ladder_rung=RUNG_NOTHING,
        )


def compare(verdict: Verdict, arbiter: ArbiterCheck) -> ArbiterAgreement:
    """What the model's verdict and the table's answer add up to.

    Four values, and the two kinds of silence are the point. The table
    abstaining is `not_checked`: nothing checked this fact and it says so. A
    model answering `partially_confirms`, `unrelated` or `insufficient_evidence`
    is `not_comparable`, because the table has two values and those are
    refinements it cannot speak to - calling that a disagreement would
    manufacture a conflict out of a vocabulary mismatch.

    Agreement is recorded as well as disagreement. *The deterministic check
    agreed* is a publishable property of a fact, and the absence of a check
    must never read like a passed one.
    """

    if arbiter.verdict is None:
        return ArbiterAgreement.NOT_CHECKED
    if verdict not in CONCLUSIVE_VERDICTS:
        return ArbiterAgreement.NOT_COMPARABLE
    if verdict is arbiter.verdict:
        return ArbiterAgreement.AGREED
    return ArbiterAgreement.DISAGREED


def _rule_refs(package: EvidencePackage) -> tuple[str, ...]:
    """The citable references for a verdict reached from the rule alone."""

    return tuple(
        item.ref
        for item in package.items
        if item.role in (EvidenceRole.RULE, EvidenceRole.PERMITTED_SET)
    )


def _why_nothing(outcome: LadderOutcome, arbiter: ArbiterCheck) -> str:
    """The sentence a reviewer reads instead of a verdict."""

    if outcome.guard_failures:
        failed = ", ".join(sorted({str(failure) for failure in outcome.guard_failures}))
        return (
            f"Every answer this fact received was rejected ({failed}), and a "
            f"rejected answer is not replaced by another judge. Nothing is "
            f"claimed about this dependency."
        )
    return (
        f"No model could be reached and the deterministic table abstained "
        f"({arbiter.basis}), so nothing checked this dependency."
    )
