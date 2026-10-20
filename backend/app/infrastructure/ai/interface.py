"""Provider- and model-agnostic AI interface.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    The one way the research code reaches a model. A caller names a task and
    hands over a schema; this resolves the task to a model, checks that model
    can do what is being asked of it, caches the result and returns it stamped
    with what actually produced it.

    The cache lives here rather than in the subcomponents that call models, so
    no subcomponent can forget it. That placement is the whole reason one
    mechanism solves four separate problems:

      * the free tier's token-per-minute limit, which a live run of a full
        release would otherwise exceed
      * demo throughput, since a warmed cache replays a whole run instantly
      * reproducibility, because a cached response is provably the one the
        model gave for that exact prompt, model and evidence
      * iteration speed, as changing code downstream of a verdict no longer
        means paying for the verdict again

    The key is a hash of prompt version, model id, schema mode, evidence hash
    and task. Everything that could change the answer is in the key, so a hit
    is only ever a hit on the identical question - which means there is no
    invalidation logic to write or to get wrong.
"""

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from app.domain.model_access import ModelResponseUnusable, ModelUnavailable

from .call_log import (
    OUTCOME_ANSWERED,
    OUTCOME_REPLAYED,
    OUTCOME_UNAVAILABLE,
    OUTCOME_UNUSABLE,
)
from .model_configuration import (
    SCHEMA_MODE_STRICT,
    TASK_PRIMARY_VERDICT_LOCAL,
    AISettings,
    ai_settings,
)
from .model_registry import capabilities_for
from .providers.openai_compatible import ProviderContentError, ProviderError


@dataclass(frozen=True)
class AIResult:
    """One model response, with everything needed to reproduce it.

    `model_id` is what the provider reported, not what was requested: a
    provider can serve a different build under the same name, and a result
    stamped with the request cannot be reproduced.
    """

    content: dict
    model_id: str
    prompt_version: str
    schema_mode: str
    cached: bool
    task: str


class StrictSchemaUnsupportedError(RuntimeError):
    """Strict output was requested from a model that cannot guarantee it.

    Raised rather than silently downgrading to best-effort. Best-effort returns
    an error when the model misses the schema, so a quiet downgrade would turn
    every schema miss into a failed request and the retry logic would be
    reasoning about the wrong failure.
    """

    def __init__(self, model_id: str) -> None:
        super().__init__(
            f"Model '{model_id}' does not support strict JSON-schema output. "
            "Choose a model from model_registry.strict_schema_models(), or set "
            "ai_schema_mode=best_effort deliberately."
        )
        self.model_id = model_id


class VerdictCache:
    """Content-addressed store of model responses.

    One JSON file per entry, named by the key. A directory of small files
    rather than a database because the access pattern is get-by-exact-key and
    nothing else, and because an entry can be read, diffed and deleted by hand
    while the pipeline is being built.
    """

    def __init__(self, directory: Path | str, enabled: bool = True) -> None:
        self._directory = Path(directory)
        self._enabled = enabled
        self._memory: dict[str, dict] = {}

    @staticmethod
    def key(
        task: str,
        prompt_version: str,
        model_id: str,
        schema_mode: str,
        evidence_hash: str,
    ) -> str:
        """Build the cache key.

        A joined string with an explicit separator, so the key cannot depend on
        dict ordering and so adding a component later is a deliberate change to
        every key rather than an accidental one.
        """

        material = "|".join((task, prompt_version, model_id, schema_mode, evidence_hash))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict | None:
        if not self._enabled:
            return None
        if key in self._memory:
            return self._memory[key]

        path = self._path(key)
        if not path.exists():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A corrupt entry is a miss, not a failure. The cache is an
            # optimisation, and a run that dies because a cache file was
            # truncated would be a worse outcome than paying for the call.
            return None
        self._memory[key] = entry
        return entry

    def put(self, key: str, entry: dict) -> None:
        if not self._enabled:
            return
        self._memory[key] = entry
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            self._path(key).write_text(
                json.dumps(entry, indent=2, sort_keys=True), encoding="utf-8"
            )
        except OSError:
            # Writing is best-effort for the same reason reading is: the
            # in-memory copy still serves this run.
            pass

    def _path(self, key: str) -> Path:
        return self._directory / f"{key}.json"


class ConfiguredAIClient:
    """Resolves a task to a model, caches the response, stamps the result."""

    def __init__(
        self,
        provider,
        settings: AISettings | None = None,
        cache: VerdictCache | None = None,
        local_provider=None,
        call_log=None,
    ) -> None:
        """`call_log` is optional because nothing in a run depends on it.

        It is written to on every path through `complete` and read by nothing
        here, which is the property that lets it be left out of a test without
        changing what the test is measuring.
        """

        self._provider = provider
        self._settings = settings or ai_settings
        self._cache = cache or VerdictCache(
            self._settings.ai_cache_directory, self._settings.ai_cache_enabled
        )
        self._local_provider = local_provider
        self._call_log = call_log

    def _provider_for(self, task: str):
        """Return the adapter that reaches `task`'s endpoint.

        Two adapters rather than one because they differ in the only thing an
        adapter holds: the URL. The alternative - one adapter told the URL per
        call - would put the endpoint in the caller's hands, and the caller is
        the thing that is not allowed to know where a model lives.

        With no local runtime configured this raises the same error a dead
        network raises, which is the truth: the rung cannot answer. The ladder
        then moves past it, as it already did when the local model id was
        being posted to the hosted provider.
        """

        if task != TASK_PRIMARY_VERDICT_LOCAL:
            return self._provider
        if self._local_provider is None:
            raise ModelUnavailable(
                "No local runtime is configured. Set ai_local_base_url to reach one."
            )
        return self._local_provider

    def complete(
        self,
        task: str,
        prompt: str,
        schema: dict,
        prompt_version: str = "unversioned",
        evidence_hash: str = "",
    ) -> AIResult:
        """Answer `task`, from cache when the question is identical.

        `prompt_version` and `evidence_hash` are part of the key rather than
        the prompt text, so an edited prompt file or a changed evidence package
        misses the cache automatically. Hashing the prompt string instead would
        work too, and would hide which of the two changed.
        """

        model_id = self._settings.model_for(task)
        schema_mode = self._settings.ai_schema_mode
        strict = schema_mode == SCHEMA_MODE_STRICT

        if strict and not capabilities_for(model_id).supports_strict_schema:
            raise StrictSchemaUnsupportedError(model_id)

        key = VerdictCache.key(task, prompt_version, model_id, schema_mode, evidence_hash)
        started = time.perf_counter()
        cached = self._cache.get(key)
        if cached is not None:
            self._log(
                task,
                model_id,
                cached["model_id"],
                prompt,
                prompt_version,
                schema_mode,
                evidence_hash,
                OUTCOME_REPLAYED,
                started,
                response=cached["content"],
            )
            return AIResult(
                content=cached["content"],
                model_id=cached["model_id"],
                prompt_version=prompt_version,
                schema_mode=schema_mode,
                cached=True,
                task=task,
            )

        try:
            response = self._provider_for(task).complete(
                model_id=model_id,
                prompt=prompt,
                schema=schema,
                strict=strict,
                temperature=self._settings.ai_temperature,
                seed=self._settings.ai_seed,
            )
        except ProviderContentError as error:
            # Translated here, because this is the last place that knows which
            # provider raised and the first place whose errors a component is
            # allowed to catch. The two are kept apart all the way through:
            # one is a reason to try another model and the other is not.
            self._log(
                task,
                model_id,
                model_id,
                prompt,
                prompt_version,
                schema_mode,
                evidence_hash,
                OUTCOME_UNUSABLE,
                started,
                error=str(error),
            )
            raise ModelResponseUnusable(str(error)) from error
        except ProviderError as error:
            # Logged before it is translated, because the sentence the
            # provider gave is the only thing that says *why* a rung went
            # unanswered, and the ladder above keeps the rung and discards it.
            self._log(
                task,
                model_id,
                model_id,
                prompt,
                prompt_version,
                schema_mode,
                evidence_hash,
                OUTCOME_UNAVAILABLE,
                started,
                error=str(error),
            )
            raise ModelUnavailable(str(error)) from error

        self._log(
            task,
            model_id,
            response["model_id"],
            prompt,
            prompt_version,
            schema_mode,
            evidence_hash,
            OUTCOME_ANSWERED,
            started,
            response=response["content"],
            usage=response.get("usage"),
        )

        self._cache.put(
            key,
            {
                "content": response["content"],
                "model_id": response["model_id"],
                "task": task,
                "prompt_version": prompt_version,
                "schema_mode": schema_mode,
                "evidence_hash": evidence_hash,
            },
        )

        return AIResult(
            content=response["content"],
            model_id=response["model_id"],
            prompt_version=prompt_version,
            schema_mode=schema_mode,
            cached=False,
            task=task,
        )

    def _log(
        self,
        task: str,
        requested_model: str,
        answered_model: str,
        prompt: str,
        prompt_version: str,
        schema_mode: str,
        evidence_hash: str,
        outcome: str,
        started: float,
        response: dict | None = None,
        error: str | None = None,
        usage: dict | None = None,
    ) -> None:
        """Record one call, when something is capturing.

        Deliberately the last statement on every path rather than a decorator
        or a wrapper: a failed call and a replayed one carry different fields,
        and a wrapper that could see only the return value would record the
        two cases it exists to tell apart as one.
        """

        if self._call_log is None:
            return

        self._call_log.record(
            task=task,
            requested_model=requested_model,
            answered_model=answered_model,
            prompt=prompt,
            prompt_version=prompt_version,
            schema_mode=schema_mode,
            evidence_hash=evidence_hash,
            outcome=outcome,
            latency_ms=int((time.perf_counter() - started) * 1000),
            response=response,
            error=error,
            usage=usage,
        )
