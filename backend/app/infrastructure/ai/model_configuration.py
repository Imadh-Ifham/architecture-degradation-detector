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

SCHEMA_MODE_STRICT = "strict"
SCHEMA_MODE_BEST_EFFORT = "best_effort"


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
    ai_verifier_model: str = "qwen/qwen3-32b"

    # The reasoner's two fallbacks. The first is a larger sibling on the same
    # provider, for when the configured model is the thing that is down; the
    # second is a local runtime, for when the network is. Both are chosen for
    # availability rather than for quality, and a verdict says which answered.
    ai_fallback_model: str = "openai/gpt-oss-120b"
    ai_local_model: str = "llama3.2:3b"

    ai_schema_mode: str = SCHEMA_MODE_STRICT
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
        }
        if task not in mapping:
            raise UnknownTaskError(task, tuple(mapping))
        return mapping[task]


class UnknownTaskError(KeyError):
    """A task has no model assigned to it."""

    def __init__(self, task: str, known: tuple[str, ...]) -> None:
        super().__init__(
            f"No model is configured for task '{task}'. Known tasks: {', '.join(known)}."
        )
        self.task = task
        self.known = known


ai_settings = AISettings()
