"""AI model configuration.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Which model is used for which task, and how to reach the provider.

    A separate settings class rather than fields on the shared application
    settings, with an `ai_` prefix so nothing collides. The shared settings
    file is edited by everyone, and adding a block to it for one component's
    needs is how merge conflicts get manufactured. Both classes read the same
    `.env`, so this costs nothing operationally.

    Credentials come from the environment and from nowhere else. There is
    deliberately no default for the API key: a key pasted into a default is
    committed, and a committed secret stays in the history after it is
    removed.

    Tasks map to models here rather than in the subcomponents that use them.
    A subcomponent names a task; this decides what answers it. That is what
    makes the model a variable the research can change, and what satisfies the
    rule that no component depends on a specific provider or model.
"""

from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

TASK_PRIMARY_VERDICT = "primary_verdict"
TASK_VERIFICATION = "verification"

TASK_PRIMARY_VERDICT_FALLBACK = "primary_verdict_fallback"
TASK_PRIMARY_VERDICT_LOCAL = "primary_verdict_local"
"""The two rungs below the primary verdict, named as tasks rather than models.

The reasoner's ladder tries another model when nothing answered, and a
component may not name a model - so the rungs are tasks and this file decides
what answers them. Both are deliberately only for the reasoner: verification
must never fall back to another model, because a verifier that is not
independent of the reasoner is a model agreeing with itself.
"""

TASK_NARRATION = "run_narration"
"""Writing the plain-English account of a run that is already decided.

A task like the others so the narrator cannot name a model either, and
deliberately not one of the judges: nothing it produces reaches a verdict, a
confidence or the published graph. It is listed here rather than left to the
reasoner's model because it is one call per run instead of one per fact, so
the larger model costs almost nothing and reads better.
"""

SCHEMA_MODE_STRICT = "strict"
SCHEMA_MODE_BEST_EFFORT = "best_effort"
SCHEMA_MODE_JSON_OBJECT = "json_object"
"""The only shape some providers serve, and a different guarantee entirely.

`strict` and `best_effort` both send `response_format: {"type": "json_schema"}`
and differ only in whether the schema is tightened first. A provider that does
not serve `json_schema` at all refuses both, so neither mode is a fallback for
the other - which is why there is a third rather than a looser second.

**What it gives up is the guarantee, and it is written down here so nobody has
to infer it from behaviour.** The schema is carried in the prompt instead of in
the decoder, so the model is asked rather than constrained, and the answer is
checked against the schema's required fields after it arrives. A missing field
becomes a content error, which the ladder already treats as a retryable answer
and then as `insufficient_evidence`. It never becomes a silently incomplete
verdict.
"""

SCHEMA_MODES = (SCHEMA_MODE_STRICT, SCHEMA_MODE_BEST_EFFORT, SCHEMA_MODE_JSON_OBJECT)


class AISettings(BaseSettings):
    """How this deployment reaches a model.

    The default provider speaks the OpenAI chat-completions API. So do every
    hosted and local runtime under consideration, which is why there is one
    adapter and the provider is three values rather than a code change.
    """

    ai_provider: str = "openai_compatible"
    ai_base_url: str = "https://api.groq.com/openai/v1"
    ai_api_key: str = ""

    # Two different models on purpose. The verifier exists to catch the
    # reasoner being confidently wrong, and with identical weights it would
    # share the reasoner's blind spots and mostly agree. On open-weights
    # providers the second model costs nothing, so the stronger design is free.
    ai_reasoner_model: str = "openai/gpt-oss-20b"
    # Was qwen/qwen3-32b, which the provider stopped serving by 2026-10-17.
    # Replaced rather than waited out: a verifier that 404s is a verifier that
    # silently stops verifying, and a free roster changes without notice.
    ai_verifier_model: str = "qwen/qwen3.8-27b"

    # The reasoner's two fallbacks. The first is a larger sibling on the same
    # provider, for when the configured model is the thing that is down; the
    # second is a local runtime, for when the network is. Both are chosen for
    # availability rather than for quality, and a verdict says which answered.
    ai_fallback_model: str = "openai/gpt-oss-120b"
    ai_local_model: str = "llama3.2:3b"

    ai_narrator_model: str = "openai/gpt-oss-120b"

    # Rung 4 is a different endpoint and not only a different model name. A
    # local model id posted to the hosted provider comes back as a 404, which
    # the ladder reads as an outage - so the rung appeared to exist while
    # never being able to answer. Empty means no local runtime is configured,
    # and the rung reports that instead of asking the wrong endpoint.
    ai_local_base_url: str = ""

    # The verifier's own endpoint and key, when it lives at a different
    # provider from the reasoner.
    #
    # **This is the arrangement the design has always argued for and could not
    # express.** The verifier exists to catch the reasoner being confidently
    # wrong; two models from one provider share a tokenizer, a serving stack
    # and usually a lineage, so they share blind spots. Two providers share
    # none of that, and the second opinion is worth more.
    #
    # It is also the fastest arrangement measured: the reasoner's latency and
    # the verifier's are set by different models at different providers, and
    # the slow arm of one is not the slow arm of the other.
    #
    # Empty means the verifier goes wherever everything else goes, which is
    # the single-provider configuration and still correct.
    ai_verifier_base_url: str = ""
    ai_verifier_api_key: str = ""

    # Whether a verdict with no model behind it may be produced at all.
    #
    # True is the demonstration's rollback: every model unreachable, the
    # deterministic table decides, every verdict says so. False is for any run
    # whose numbers will be reported, because without a key every governed
    # fact degrades to the table and a suite that accepted those would pass
    # while measuring nothing.
    ai_use_models: bool = True
    """Whether this deployment asks a model at all.

    True is every ordinary run. False is the rollback for a demonstration
    with no network *and* no warmed cache: the reasoner is not called, the
    verifier is not called, and every governed fact is decided by the
    deterministic table.

    It is separate from `ai_cache_enabled` because the two answer different
    questions. A warm cache makes a repeat run instant **and keeps the
    model's own verdicts**, which is what a demonstration should use. This
    flag is for when there is nothing to replay either.

    Nothing produced under `false` is allowed to look like a model answered
    it: the verdicts carry `produced_by: arbiter`, a model id of "none", and
    a sentence saying the models were not asked. A faster run that claimed
    otherwise would be presenting the table's output as a language model's.
    """

    ai_allow_arbiter_only: bool = True

    ai_reasoning_effort: str = "low"
    """How much thinking a reasoning model emits before it answers.

    Empty leaves the provider's default. `low` is the default here because
    the binding constraint on a per-minute tier is tokens, and this is the
    one dial that reduces them without shortening the evidence.

    Measured on a real verdict from the corpus: `low` spent 815 total tokens
    where the provider's default spent 1001, and returned the same verdict,
    the same citation and an equivalent reasoning sentence. The sentence is
    read by a person, so this is checked against the output rather than
    assumed - if the reasoning stops being worth reading, raise it.
    """

    ai_concurrency: int = 1
    """How many facts may be waiting on a model at once, within one release.

    **A release's time is almost entirely a socket.** Measured on seventeen
    facts: the component's own work is 1.2 seconds, of which evidence
    retrieval is 31 milliseconds, and the rest of the run is model calls made
    one after another. Overlapping them is the only lever left.

    One is the behaviour this component shipped with, and the default, so an
    unconfigured deployment runs exactly as it did. What bounds a higher value
    is the provider rather than the machine - a per-minute token tier refuses
    a burst that a paid tier absorbs - so it is a number to raise against a
    provider and then leave alone.

    Nothing that decides anything is spread: classification runs afterwards,
    in order, and the published document is identical at any setting.
    """

    ai_schema_mode: str = SCHEMA_MODE_STRICT
    """How the answer is constrained to the schema. One of `SCHEMA_MODES`.

    Validated rather than trusted. A typo here used to mean *not strict*, which
    is a quieter failure than it sounds: every call would still be made, every
    answer would still parse, and the one guarantee the design rests on would
    be absent from a run nobody could tell apart from a good one.
    """
    ai_max_output_tokens: int = 800
    """A ceiling on the answer, sent with every call.

    **Not an optimisation - without it a provider assumes its own default and
    can refuse the request outright.** Groq's on-demand tier caps some models
    at 1000 output tokens a minute and compares that cap against the
    *requested* maximum, not against what the answer turns out to be. Sending
    nothing meant 2048 was assumed, which exceeds the cap, so every call came
    back 429 with `reduce max_tokens` - a permanent refusal that the adapter
    read as a rate limit and dutifully waited out, over and over.

    800 clears that cap and is far above what any task here produces: a
    verdict is about 100 tokens and a challenge is smaller. Raise it only for
    a prompt that genuinely needs a longer answer, and check the provider's
    per-minute output limit before doing so.
    """

    ai_temperature: float = 0.0
    ai_seed: int = 42
    ai_timeout_seconds: float = 60.0
    ai_max_retries: int = 1

    # Where cached model responses are kept. Under artifacts/ because they are
    # output, and artifacts/ is not committed.
    ai_cache_directory: str = "artifacts/verdict_cache"
    ai_cache_enabled: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def model_for(self, task: str) -> str:
        """Return the model that answers `task`.

        Raises on an unknown task rather than falling back to the reasoner. A
        silent fallback would mean a new task quietly ran on the wrong model
        and the results would be mixed together with nothing recording it.
        """

        mapping = {
            TASK_PRIMARY_VERDICT: self.ai_reasoner_model,
            TASK_PRIMARY_VERDICT_FALLBACK: self.ai_fallback_model,
            TASK_PRIMARY_VERDICT_LOCAL: self.ai_local_model,
            TASK_VERIFICATION: self.ai_verifier_model,
            TASK_NARRATION: self.ai_narrator_model,
        }
        if task not in mapping:
            raise UnknownTaskError(task, tuple(mapping))
        return mapping[task]

    @field_validator("ai_schema_mode")
    @classmethod
    def _known_schema_mode(cls, value: str) -> str:
        """Refuse a schema mode nothing implements, by name."""

        if value not in SCHEMA_MODES:
            raise ValueError(
                f"AI_SCHEMA_MODE is '{value}', which is not one of "
                f"{', '.join(SCHEMA_MODES)}."
            )
        return value

    def base_url_for(self, task: str) -> str:
        """Return the endpoint that answers `task`.

        Everything hosted shares one URL. The local rung has its own, and an
        unset one means there is no local runtime rather than that the local
        model lives with the hosted ones.
        """

        if task == TASK_PRIMARY_VERDICT_LOCAL:
            return self.ai_local_base_url
        if task == TASK_VERIFICATION and self.ai_verifier_base_url:
            return self.ai_verifier_base_url
        return self.ai_base_url

    def api_key_for(self, task: str) -> str:
        """Return the key that opens `task`'s endpoint.

        **The shared key is inherited only when the two endpoints are the same
        host.** Two URLs at one host is a real arrangement - a gateway, a
        second path - and it should not need the key written twice. Two hosts
        is the opposite case: sending one provider's key to another is a 401,
        which the ladder reads as an outage, and the run then publishes every
        verdict `unverified_unavailable` while looking exactly like a run
        whose verifier was simply down.

        So a cross-provider verifier with no key of its own gets no key, and
        the adapter refuses before the request with a message naming the
        setting. An absent check must never look like a passed one, and that
        applies to the check this component is built out of.
        """

        if task == TASK_VERIFICATION and self.ai_verifier_base_url:
            if self.ai_verifier_api_key:
                return self.ai_verifier_api_key
            if _host(self.ai_verifier_base_url) == _host(self.ai_base_url):
                return self.ai_api_key
            return ""
        return self.ai_api_key


class UnknownTaskError(KeyError):
    """A task has no model assigned to it."""

    def __init__(self, task: str, known: tuple[str, ...]) -> None:
        super().__init__(
            f"No model is configured for task '{task}'. Known tasks: {', '.join(known)}."
        )
        self.task = task
        self.known = known


ai_settings = AISettings()


def _host(url: str) -> str:
    """The host an endpoint names, for deciding whether a key can be shared."""

    return urlparse(url).netloc.lower()
