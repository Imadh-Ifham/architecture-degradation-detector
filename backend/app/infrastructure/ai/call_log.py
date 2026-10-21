"""Every model call a run made, as it was made.

Author: Aman Mohamed M.A
Date: 2026-10-21
Description:
    Records the request text, the answer and what produced it, for each call
    the AI interface handles.

    It exists because of a question that could not be answered from the
    screen: a run on a machine with no key reaches the same verdicts as a run
    with one, because the deterministic table agrees with the model on the
    easy facts and every published field is identical either way. "A model was
    involved" was a claim the system made about itself and nothing could check
    it.

    So the log sits in the interface rather than in the two subcomponents that
    call models. That is the same placement argument the response cache
    already settled: the interface is the only chokepoint every call passes
    through, and a subcomponent cannot forget to use it. It also means a call
    answered from cache is recorded as a replay rather than disappearing,
    which is the case that made the original question hard - a warm cache
    makes a real run report zero calls.

    Capture is thread-local because a run is synchronous inside one request
    and the client is a process-wide singleton. A list on the client would
    collect two concurrent runs into one transcript, and neither of them would
    be wrong in any visible way.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Lock

OUTCOME_ANSWERED = "answered"
OUTCOME_REPLAYED = "replayed"
OUTCOME_UNAVAILABLE = "unavailable"
OUTCOME_UNUSABLE = "unusable"


@dataclass(frozen=True)
class ModelCall:
    """One request to one model, and what came back.

    `requested_model` and `answered_model` are both kept. A provider can serve
    a different build under the name it was asked for, and the two being equal
    is worth seeing rather than assuming.

    `response` is the parsed answer and `error` the reason there is none.
    Exactly one of them is set, which is what makes `outcome` checkable
    against the row rather than a label nobody verifies.
    """

    sequence: int
    task: str
    requested_model: str
    answered_model: str
    prompt: str
    prompt_version: str
    schema_mode: str
    evidence_hash: str
    outcome: str
    latency_ms: int
    waited_ms: int = 0
    """Of `latency_ms`, how much was spent waiting for a rate limit.

    Separated because the two look identical in a single number and mean
    opposite things. A four-second call on a per-minute tier is usually half
    a second of model and three and a half of waiting for a token budget to
    refill, and reporting that as latency makes a fast model look slow and
    sends somebody shopping for a different one.
    """

    response: dict | None = None
    error: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def to_dict(self) -> dict:
        return {
            "sequence": self.sequence,
            "task": self.task,
            "requested_model": self.requested_model,
            "answered_model": self.answered_model,
            "prompt": self.prompt,
            "prompt_version": self.prompt_version,
            "schema_mode": self.schema_mode,
            "evidence_hash": self.evidence_hash,
            "outcome": self.outcome,
            "latency_ms": self.latency_ms,
            "waited_ms": self.waited_ms,
            "answered_ms": max(self.latency_ms - self.waited_ms, 0),
            "response": self.response,
            "error": self.error,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
        }


@dataclass
class _Capture:
    """The calls collected inside one `capture()` block."""

    calls: list[ModelCall] = field(default_factory=list)


class CallLog:
    """Collects the calls made inside a `capture()` block, per thread.

    Outside a block nothing is kept. Recording unconditionally into a
    process-wide list would grow without bound in a server that never
    restarts, and the only consumer wants one run's worth.
    """

    def __init__(self) -> None:
        self._capture: ContextVar = ContextVar("call_log_capture", default=None)
        self._lock = Lock()
        """Guards the append. Workers record concurrently, and `list.append`
        being atomic today is a property of one interpreter rather than of the
        language."""

    @contextmanager
    def capture(self) -> Iterator[list[ModelCall]]:
        """Collect every call made in this context until the block ends.

        **A context variable, not a thread-local, and that is what lets a run
        fan out.** A thread-local capture is invisible to any worker the run
        starts, so a release judging its facts in parallel would publish a
        transcript missing every call it made - and this component's whole
        claim is that a model having answered is checkable.

        The list is handed over before the block runs, so a caller still has
        the calls made up to the point of a failure. A run that died halfway
        is exactly when the transcript is worth reading.
        """

        token = self._capture.set(_Capture())
        try:
            yield self._capture.get().calls
        finally:
            self._capture.reset(token)

    def record(
        self,
        task: str,
        requested_model: str,
        answered_model: str,
        prompt: str,
        prompt_version: str,
        schema_mode: str,
        evidence_hash: str,
        outcome: str,
        latency_ms: int,
        response: dict | None = None,
        error: str | None = None,
        usage: dict | None = None,
        waited_seconds: float = 0.0,
    ) -> None:
        """Add one call to the capture in progress, if there is one."""

        current = self._capture.get()
        if current is None:
            return

        tokens = usage or {}
        with self._lock:
            current.calls.append(
                ModelCall(
                    sequence=len(current.calls) + 1,
                    task=task,
                    requested_model=requested_model,
                    answered_model=answered_model,
                    prompt=prompt,
                    prompt_version=prompt_version,
                    schema_mode=schema_mode,
                    evidence_hash=evidence_hash,
                    outcome=outcome,
                    latency_ms=latency_ms,
                    waited_ms=int(waited_seconds * 1000),
                    response=response,
                    error=error,
                    prompt_tokens=int(tokens.get("prompt_tokens") or 0),
                    completion_tokens=int(tokens.get("completion_tokens") or 0),
                )
            )


def summarise(calls: list[ModelCall]) -> dict:
    """The counts a reader checks before reading any individual call.

    `live` and `replayed` are separate because together they answer the
    question the log was written for, and neither answers it alone: live calls
    prove a model was reached on this run, and replays prove the answers came
    from one on an earlier run rather than from the table.
    """

    return {
        "calls": len(calls),
        "live": len([call for call in calls if call.outcome == OUTCOME_ANSWERED]),
        "replayed": len([call for call in calls if call.outcome == OUTCOME_REPLAYED]),
        "unavailable": len(
            [call for call in calls if call.outcome == OUTCOME_UNAVAILABLE]
        ),
        "unusable": len([call for call in calls if call.outcome == OUTCOME_UNUSABLE]),
        "prompt_tokens": sum(call.prompt_tokens for call in calls),
        "completion_tokens": sum(call.completion_tokens for call in calls),
        "waited_ms": sum(call.waited_ms for call in calls),
        "answered_ms": sum(
            max(call.latency_ms - call.waited_ms, 0) for call in calls
        ),
    }


__all__ = [
    "OUTCOME_ANSWERED",
    "OUTCOME_REPLAYED",
    "OUTCOME_UNAVAILABLE",
    "OUTCOME_UNUSABLE",
    "CallLog",
    "ModelCall",
    "summarise",
]
