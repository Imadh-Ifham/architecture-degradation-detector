"""AI model registry.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    What is known about each model, independent of which task uses it.

    One capability matters more than the rest: whether the model supports
    strict JSON-schema output. Strict mode constrains decoding, so a response
    that violates the schema is impossible rather than caught. Best-effort mode
    returns an error when the model misses the schema, which turns a retryable
    condition into a failed request and makes the retry semantics meaningless.

    So a model without strict support is not a slower option here, it is a
    different design. The registry records the difference instead of leaving it
    to be discovered at runtime.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelCapabilities:
    """What a model can be relied on to do.

    `context_tokens` is recorded because the evidence budget is bounded by it,
    and `free_tier` because the demo's throughput plan depends on which
    models cost nothing.
    """

    model_id: str
    supports_strict_schema: bool
    context_tokens: int
    free_tier: bool
    supports_reasoning_effort: bool = False
    """Whether `reasoning_effort` means what it says to this model.

    It is an OpenAI parameter, and on the gpt-oss models `low` does what it
    promises: measured on a real verdict, 82 completion tokens against 223.

    **On a model that does not take it, sending it is not ignored - it is
    worse than not sending it.** The verifier emitted 821 completion tokens
    with `low` and 40 with the field absent, so the one dial added to save
    tokens was doubling the cost of the call that was already the expensive
    one. Recorded here rather than guessed, which is this file's whole job.
    """

    notes: str = ""


_KNOWN = (
    ModelCapabilities(
        model_id="openai/gpt-oss-20b",
        supports_strict_schema=True,
        context_tokens=131_072,
        free_tier=True,
        supports_reasoning_effort=True,
        notes="Default reasoner. Strict schema support is the reason it is the default.",
    ),
    ModelCapabilities(
        model_id="openai/gpt-oss-120b",
        supports_strict_schema=True,
        context_tokens=131_072,
        free_tier=True,
        supports_reasoning_effort=True,
        notes="Larger sibling. Same strict support, lower rate limit.",
    ),
    ModelCapabilities(
        model_id="qwen/qwen3.8-27b",
        supports_strict_schema=True,
        context_tokens=131_072,
        free_tier=True,
        notes=(
            "Default verifier. Different weights from the reasoner, which is the point. "
            "Succeeds qwen/qwen3-32b, off the provider's roster by 2026-10-17; strict "
            "output confirmed against the live endpoint on that date."
        ),
    ),
    ModelCapabilities(
        model_id="llama-3.3-70b-versatile",
        supports_strict_schema=False,
        context_tokens=131_072,
        free_tier=True,
        notes="No strict schema. Recorded so it is not chosen by mistake.",
    ),
    # DeepSeek, reached through the same OpenAI-compatible adapter at
    # https://api.deepseek.com/v1. Registered so the provider can be swapped in
    # .env, and registered with `supports_strict_schema=False` because that is
    # what its API documents: `response_format` takes `json_object`, and
    # `json_schema` is not among its values. Strict schema enforcement exists
    # there only for tool-call arguments, on a separate beta endpoint, which is
    # a different request shape and not what any task here sends.
    #
    # So these models run under `AI_SCHEMA_MODE=json_object` and under nothing
    # else - and the alternative to recording that here is finding it out from
    # a 400 in the middle of a demonstration.
    ModelCapabilities(
        model_id="deepseek-chat",
        supports_strict_schema=False,
        context_tokens=65_536,
        free_tier=False,
        notes=(
            "DeepSeek's general model. JSON object mode only. Context recorded "
            "conservatively: the evidence budget is bounded by it, so a figure "
            "that is too small costs a little evidence and one that is too "
            "large costs the call."
        ),
    ),
    ModelCapabilities(
        model_id="deepseek-reasoner",
        supports_strict_schema=False,
        context_tokens=65_536,
        free_tier=False,
        notes=(
            "DeepSeek's reasoning model. JSON object mode only. It emits its "
            "own reasoning before the answer, so it is the expensive one on a "
            "per-token price list - not a free second opinion."
        ),
    ),
    ModelCapabilities(
        model_id="deepseek-flash",
        supports_strict_schema=False,
        context_tokens=65_536,
        free_tier=False,
        notes=(
            "The model named in DeepSeek's own JSON-output example. JSON object "
            "mode only."
        ),
    ),
    ModelCapabilities(
        model_id="llama3.2:3b",
        supports_strict_schema=True,
        context_tokens=131_072,
        free_tier=True,
        notes="Offline fallback, sized for a 4 GB GPU. For availability, not quality.",
    ),
)

_BY_ID = {capability.model_id: capability for capability in _KNOWN}


class UnknownModelError(KeyError):
    """A model is configured that the registry knows nothing about."""

    def __init__(self, model_id: str) -> None:
        super().__init__(
            f"Model '{model_id}' is not in the registry. Add it to model_registry.py "
            "with its strict-schema support before using it."
        )
        self.model_id = model_id


def capabilities_for(model_id: str) -> ModelCapabilities:
    """Return what is known about `model_id`.

    Raises rather than assuming. An unregistered model would otherwise be used
    with strict schema requested and no record of whether it supports it, and
    the resulting failures would look like prompt problems.
    """

    if model_id not in _BY_ID:
        raise UnknownModelError(model_id)
    return _BY_ID[model_id]


def strict_schema_models() -> tuple[str, ...]:
    """Every registered model that can be relied on for strict output."""

    return tuple(
        capability.model_id for capability in _KNOWN if capability.supports_strict_schema
    )
