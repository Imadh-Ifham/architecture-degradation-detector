"""The bounded fallback sequence, and the two rules that keep it a ladder.

Author: Aman Mohamed M.A
Date: 2026-10-16
Description:
    One fact can be asked of several things before the component gives up, in
    a fixed order, each of them once:

      0  the warmed cache          no call. The client answers from disk
      1  the first task's model    the normal path
      2  the same model again      identical input, after a guard rejected it
      3  the next task's model     only because nothing answered
      4  the task after that       only because nothing answered

    Above rung 4 there is no model left, and what happens then is the
    service's decision rather than the ladder's.

    **Two rules, and they are what make this a ladder rather than a loop.**

    A guard failure may move *down* to the identical retry and never *across*
    to another model. A second model answering a question the first one
    botched is a different question, so no comparison between the two would
    mean anything - and a pipeline that quietly shops around until some model
    produces an acceptable answer is selecting for agreeable models rather
    than measuring them.

    A model that could not be reached is never retried at the same rung. The
    thing that just failed is the thing that would fail again, and on a
    tokens-per-minute free tier an unbounded ladder is how a demonstration
    exhausts its budget while appearing to work.

    Together they bound one fact at **three calls**, which is tighter than the
    four the design budgeted: the retry exists only on the first rung, so the
    longest path is first-rung failure, next model, model after that.
"""

from dataclasses import dataclass
from collections.abc import Callable, Sequence

from app.domain.model_access import ModelResponseUnusable, ModelUnavailable

from ..models import AIResult, GuardFailure
from .models import GuardOutcome

RUNG_CACHE = 0
RUNG_PRIMARY = 1
RUNG_RETRY = 2
RUNG_SECONDARY = 3
RUNG_ARBITER = 5
RUNG_NOTHING = 6


@dataclass(frozen=True)
class LadderOutcome:
    """What the climb produced, and everything it had to do on the way.

    `result` is None when no rung produced an acceptable answer, and the two
    reasons for that are not interchangeable: `unavailable` non-empty means
    nothing answered, which leaves the arbiter as the only judge, while
    `guard_failures` alone means a model answered and its answer could not be
    used, which must not be replaced by the table - that would hide a bad
    model behind a good answer.
    """

    result: AIResult | None
    rung: int
    guard_failures: tuple[GuardFailure, ...] = ()
    refs_at_fault: tuple[str, ...] = ()
    attempted: tuple[str, ...] = ()
    unavailable: tuple[str, ...] = ()
    retried: bool = False


def climb(
    ai,
    tasks: Sequence[str],
    *,
    prompt: str,
    schema: dict,
    prompt_version: str,
    evidence_hash: str,
    accept: Callable[[dict], GuardOutcome],
) -> LadderOutcome:
    """Ask each rung in turn until one answer is accepted.

    `tasks` is the order to try, named as tasks rather than models because a
    component may not choose a model. One task is a complete ladder on its own
    - the cache, the model and the retry - which is what verification uses,
    since it must never fall back to another model at all.
    """

    guard_failures: list[GuardFailure] = []
    refs_at_fault: tuple[str, ...] = ()
    attempted: list[str] = []
    unavailable: list[str] = []
    retried = False

    for rung, task in _plan(tasks):
        if rung == RUNG_RETRY and not guard_failures:
            # The retry exists for a rejected answer. Nothing was rejected.
            continue
        if rung >= RUNG_SECONDARY and guard_failures:
            break

        retried = retried or rung == RUNG_RETRY
        attempted.append(task)
        try:
            result = ai.complete(
                task=task,
                prompt=prompt,
                schema=schema,
                prompt_version=prompt_version,
                evidence_hash=evidence_hash,
            )
        except ModelResponseUnusable as error:
            # Something answered and the answer could not be read, which is
            # guard A's finding arriving as an exception because the content
            # never parsed. Treated as a rejection, so it retries identically
            # and then stops, instead of moving to another model.
            guard_failures.append(GuardFailure.MALFORMED)
            refs_at_fault = refs_at_fault or (str(error)[:120],)
            continue
        except ModelUnavailable as error:
            unavailable.append(f"{task}: {error}")
            continue

        outcome = accept(result.content)
        if outcome.accepted:
            return LadderOutcome(
                result=result,
                rung=RUNG_CACHE if result.cached else rung,
                guard_failures=tuple(guard_failures),
                refs_at_fault=refs_at_fault,
                attempted=tuple(attempted),
                unavailable=tuple(unavailable),
                retried=retried,
            )

        if outcome.failure is not None:
            guard_failures.append(outcome.failure)
        refs_at_fault = outcome.refs_at_fault or refs_at_fault

    return LadderOutcome(
        result=None,
        rung=RUNG_ARBITER if not guard_failures else RUNG_NOTHING,
        guard_failures=tuple(guard_failures),
        refs_at_fault=refs_at_fault,
        attempted=tuple(attempted),
        unavailable=tuple(unavailable),
        retried=retried,
    )


def _plan(tasks: Sequence[str]) -> tuple[tuple[int, str], ...]:
    """Every (rung, task) in the order they would be tried.

    Written out rather than decided while climbing, so the sequence can be
    read, and so the retry's position - on the first task only - is a property
    of the plan instead of a condition somebody can move.
    """

    first, rest = tasks[0], tasks[1:]
    return (
        (RUNG_PRIMARY, first),
        (RUNG_RETRY, first),
        *((RUNG_SECONDARY + position, task) for position, task in enumerate(rest)),
    )


__all__ = [
    "RUNG_ARBITER",
    "RUNG_CACHE",
    "RUNG_NOTHING",
    "RUNG_PRIMARY",
    "RUNG_RETRY",
    "RUNG_SECONDARY",
    "LadderOutcome",
    "climb",
]
