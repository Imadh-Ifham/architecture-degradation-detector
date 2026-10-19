"""Independent verification service.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Re-examines a verdict as a challenge to it, using a different model.

    Research module: M5.
"""

from ..models import (
    AIResult,
    BlindVerdict,
    EvidencePackage,
    PrimaryVerdict,
    PromptTemplate,
    Verdict,
    Verification,
    VerificationOutcome,
)
from ..validation_reasoning._guards import check as check_verdict
from ..validation_reasoning._ladder import LadderOutcome, climb
from ..validation_reasoning._prompt import render as render_blind
from ..validation_reasoning._prompt import verdict_schema
from ._guards import check, objections_from
from ._prompt import render, verification_schema
from .models import MECHANISM_BLIND_VERDICT, MECHANISM_CRITICAL_REFRAMING

NO_FAULT_FOUND = "No fault was found in the argument."

NO_BLIND_PROMPT = (
    "No blind prompt is configured, so this service cannot run the blind arm. "
    "Pass blind_prompt to enable it."
)


class IndependentVerificationService:
    """Re-examines a verdict as a challenge to it, using a different model."""

    def __init__(
        self,
        ai,
        prompt: PromptTemplate,
        task: str,
        provider: str = "",
        blind_prompt: PromptTemplate | None = None,
    ) -> None:
        """Takes the model port, the loaded prompt and the one task to ask.

        **`task` is a single string and not a sequence, and that is the
        structural half of [VER-D8].** M4 takes an ordered list of tasks
        because it is allowed to try another model when nothing answers. This
        one is not: falling back to the reasoner's model would produce a
        verification that looks entirely real while being the first model
        endorsing its own answer, which is the most misleading output this
        component could emit. A parameter that cannot hold a second task
        cannot be given one by somebody who has not read this paragraph.

        Everything else is for the same reasons as M4's: the prompt arrives as
        data because a component may not open a file, and the rung arrives as
        a task name because a component may not choose a model.

        `blind_prompt` defaults to `None`, which is what keeps the blind arm
        separable: a service built without it has no blind arm and the two
        methods that need one refuse rather than improvise. **The same
        `task`** serves both arms deliberately - a third model would make the
        anchoring delta partly family and partly anchoring and would measure
        neither.
        """

        self._ai = ai
        self._prompt = prompt
        self._task = task
        self._provider = provider
        self._blind_prompt = blind_prompt

    def verify(
        self, verdict: PrimaryVerdict, package: EvidencePackage
    ) -> Verification | None:
        """Challenges a primary verdict against the same evidence.

        Poses the verdict back as something to find fault with, using a
        different model from the reasoner - which costs nothing on open-weights
        providers and is the difference between a check and a second opinion
        from the same source.

        Records the mechanism used, so results from different weeks stay
        comparable when the mechanism itself becomes the subject of study.

        Can only lower an outcome, never raise one. The verifier saw the same
        evidence, so agreement says something about the models rather than
        about the architecture.

        **The ladder is three rungs because it is given one task.** Cache,
        model, identical retry, stop - which is what `climb` does with a
        single-entry sequence, so the truncation is a property of the argument
        rather than a condition inside a loop.

        **Returns `None` when nothing answered**, and an `UNCERTAIN`
        verification when something answered and every answer was rejected.
        The two are different findings and neither is agreement: the first is
        *this check could not run*, the second is *this check ran and could
        not be used*.
        """

        outcome = climb(
            self._ai,
            (self._task,),
            prompt=render(self._prompt, package, verdict),
            schema=verification_schema(),
            prompt_version=self._prompt.version,
            evidence_hash=package.evidence_hash,
            accept=lambda content: check(content, package),
        )

        if outcome.result is not None:
            return self._from_model(verdict, package, outcome, outcome.result)
        if outcome.guard_failures:
            return self._rejected(verdict, package, outcome)
        return None

    def _from_model(
        self,
        verdict: PrimaryVerdict,
        package: EvidencePackage,
        outcome: LadderOutcome,
        result: AIResult,
    ) -> Verification:
        """The normal path: the verifier answered and all three guards passed."""

        return Verification(
            fact_id=package.fact_id,
            outcome=VerificationOutcome(result.content["outcome"]),
            mechanism=MECHANISM_CRITICAL_REFRAMING,
            reasoning=result.content["reasoning"],
            model_id=result.model_id,
            prompt_version=result.prompt_version,
            cached=result.cached,
            objections=objections_from(result.content),
            challenged_model_id=verdict.model_id,
            evidence_hash=package.evidence_hash,
            provider=self._provider,
            schema_mode=result.schema_mode,
            retried=outcome.retried,
            guard_failures=outcome.guard_failures,
        )

    def _rejected(
        self,
        verdict: PrimaryVerdict,
        package: EvidencePackage,
        outcome: LadderOutcome,
    ) -> Verification:
        """Something answered twice and neither answer could be used.

        `UNCERTAIN`, never `AGREE`, for the same reason M4 never degrades to
        `confirms`: a system that resolves its own confusion in the
        reassuring direction produces output indistinguishable from output it
        is sure about.

        It carries no objections. An incoherent answer may well have held
        three good faults with the wrong label on them, and keeping them would
        mean publishing objections under an outcome the model did not pair
        them with. The guard failures are published instead, because the rate
        of each is a result about the model rather than an incident in a log.
        """

        failed = ", ".join(sorted({str(failure) for failure in outcome.guard_failures}))

        return Verification(
            fact_id=package.fact_id,
            outcome=VerificationOutcome.UNCERTAIN,
            mechanism=MECHANISM_CRITICAL_REFRAMING,
            reasoning=(
                f"Every answer this challenge received was rejected ({failed}), "
                f"so nothing is claimed about the argument. This is not "
                f"agreement with it."
            ),
            model_id=outcome.result.model_id if outcome.result else "",
            prompt_version=self._prompt.version,
            cached=False,
            challenged_model_id=verdict.model_id,
            evidence_hash=package.evidence_hash,
            provider=self._provider,
            schema_mode="",
            retried=outcome.retried,
            guard_failures=outcome.guard_failures,
        )

    def verify_blind(self, package: EvidencePackage) -> BlindVerdict | None:
        """Ask the verifier for its own verdict, without showing it the primary's.

        **It takes the package and nothing else, and that signature is the
        whole safety argument.** A blind prompt that leaked the verdict would
        not fail and would not warn: the two arms would converge, the delta
        would collapse toward zero, and the number would read as *anchoring
        does not happen here* - a wrong result that looks like a finding. This
        method cannot leak one because it is never given one, which is a
        stronger guarantee than a request object that merely lacks a field.

        It reuses **M4's renderer, M4's schema and M4's guards unchanged**,
        because its output is a verdict in M4's five-word vocabulary. A
        hallucinating blind verifier is caught by the same code that catches a
        hallucinating reasoner, and a second implementation of one guarantee
        is how two of them come to disagree.

        Returns `None` when nothing answered, for the same reason the informed
        arm does: an absent opinion is absent, and never agreement.
        """

        if self._blind_prompt is None:
            raise ValueError(NO_BLIND_PROMPT)

        outcome = climb(
            self._ai,
            (self._task,),
            prompt=render_blind(self._blind_prompt, package),
            schema=verdict_schema(),
            prompt_version=self._blind_prompt.version,
            evidence_hash=package.evidence_hash,
            accept=lambda content: check_verdict(content, package),
        )

        if outcome.result is None:
            return None
        return self._blind_from_model(package, outcome, outcome.result)

    def verify_both(
        self, verdict: PrimaryVerdict, package: EvidencePackage
    ) -> tuple[Verification | None, BlindVerdict | None]:
        """Run both arms over one package, and hand back both answers.

        Three model calls a fact where the informed arm alone is two, which is
        why this is a measurement mode rather than a demonstration one.

        Returned as a pair rather than combined, because combining them is a
        judgement this subcomponent is not entitled to make: the difference
        between the arms is the result, and what it means to a confidence
        score is M6's decision.
        """

        return self.verify(verdict, package), self.verify_blind(package)

    def _blind_from_model(
        self,
        package: EvidencePackage,
        outcome: LadderOutcome,
        result: AIResult,
    ) -> BlindVerdict:
        """An accepted blind answer, in the shape that cannot be mistaken for
        the published verdict."""

        return BlindVerdict(
            fact_id=package.fact_id,
            verdict=Verdict(result.content["verdict"]),
            reasoning=result.content["reasoning"],
            cited_evidence_refs=tuple(result.content["cited_evidence_refs"]),
            evidence_hash=package.evidence_hash,
            model_id=result.model_id,
            prompt_version=result.prompt_version,
            cached=result.cached,
            mechanism=MECHANISM_BLIND_VERDICT,
            provider=self._provider,
            schema_mode=result.schema_mode,
            retried=outcome.retried,
            guard_failures=outcome.guard_failures,
        )
