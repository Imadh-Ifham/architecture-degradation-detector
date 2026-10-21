"""AI interface, cache and provider tests.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Covers the one way research code reaches a model.

    Every test uses the fake provider. The suite must not depend on a network,
    a key or a free tier's quota: a test that fails because somebody else
    exhausted a rate limit teaches nothing and gets ignored, which is worse
    than not having it.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

import httpx
import pytest
from pydantic import ValidationError

from app.domain.model_access import ModelUnavailable
from app.infrastructure.ai.interface import (
    ConfiguredAIClient,
    StrictSchemaUnsupportedError,
    VerdictCache,
)
from app.infrastructure.ai.model_configuration import (
    SCHEMA_MODE_BEST_EFFORT,
    SCHEMA_MODE_JSON_OBJECT,
    SCHEMA_MODE_STRICT,
    SCHEMA_MODES,
    TASK_PRIMARY_VERDICT,
    TASK_PRIMARY_VERDICT_LOCAL,
    TASK_VERIFICATION,
    AISettings,
    UnknownTaskError,
)
from app.infrastructure.ai.model_registry import (
    UnknownModelError,
    capabilities_for,
    strict_schema_models,
)
from app.infrastructure.ai.providers.fake import FakeProvider
from app.infrastructure.ai.call_log import CallLog
from app.infrastructure.ai.providers.openai_compatible import (
    FALLBACK_WAIT_SECONDS,
    MAX_RATE_LIMIT_WAITS,
    MAX_WAIT_SECONDS,
    OpenAICompatibleProvider,
    ProviderContentError,
    ProviderError,
    ProviderRateLimited,
    strictify,
)

VERDICT = {"verdict": "confirms", "cited_evidence_refs": ["ev:1"]}


def settings(tmp_path, **overrides) -> AISettings:
    values = {
        "ai_api_key": "test-key",
        "ai_cache_directory": str(tmp_path / "cache"),
        "ai_reasoner_model": "openai/gpt-oss-20b",
        "ai_verifier_model": "qwen/qwen3.8-27b",
            # Pinned, not inherited. `AISettings` reads the developer's .env, so
        # leaving this out made three cache tests pass or fail according to a
        # file that is not in the repository - which is the same complaint
        # this module's docstring already makes about keys and rate limits.
        "ai_cache_enabled": True,
    }
    values.update(overrides)
    return AISettings(**values)


def client(tmp_path, provider=None, **overrides) -> ConfiguredAIClient:
    configuration = settings(tmp_path, **overrides)
    return ConfiguredAIClient(
        provider or FakeProvider(VERDICT),
        settings=configuration,
        cache=VerdictCache(configuration.ai_cache_directory, configuration.ai_cache_enabled),
    )


class TestTaskToModelResolution:
    """A caller names a task; configuration decides what answers it."""

    def test_each_task_resolves_to_its_own_model(self, tmp_path):
        configuration = settings(tmp_path)

        assert configuration.model_for(TASK_PRIMARY_VERDICT) == "openai/gpt-oss-20b"
        assert configuration.model_for(TASK_VERIFICATION) == "qwen/qwen3.8-27b"

    def test_the_reasoner_and_verifier_are_different_models_by_default(self, tmp_path):
        """With identical weights the verifier would share the reasoner's blind
        spots and mostly agree, which would make the whole unit decorative."""

        configuration = settings(tmp_path)

        assert configuration.model_for(TASK_PRIMARY_VERDICT) != configuration.model_for(
            TASK_VERIFICATION
        )

    def test_an_unknown_task_raises_rather_than_falling_back(self, tmp_path):
        """A silent fallback would run a new task on the wrong model and mix
        the results in with nothing recording it."""

        with pytest.raises(UnknownTaskError):
            settings(tmp_path).model_for("summarise_everything")

    def test_the_caller_passes_a_task_and_never_a_model(self, tmp_path):
        provider = FakeProvider(VERDICT)

        client(tmp_path, provider).complete(
            task=TASK_PRIMARY_VERDICT, prompt="p", schema={"type": "object"}
        )

        assert provider.calls[0]["model_id"] == "openai/gpt-oss-20b"


class TestTheLocalEndpoint:
    """The local rung is a second URL, and that is the whole of what it is.

    Before this existed the rung resolved to a local model id and posted it to
    the hosted provider, which does not serve it. The 404 arrived as
    `ModelUnavailable`, the ladder moved past it, and the rung looked present
    while being unable ever to answer - the failure Rule 7 is about, since an
    absent fallback read as a working one.
    """

    def test_the_hosted_tasks_share_one_endpoint(self, tmp_path):
        configured = settings(tmp_path, ai_local_base_url="http://localhost:11434/v1")

        assert configured.base_url_for(TASK_PRIMARY_VERDICT) == configured.ai_base_url
        assert configured.base_url_for(TASK_VERIFICATION) == configured.ai_base_url

    def test_the_local_task_resolves_to_the_local_endpoint(self, tmp_path):
        configured = settings(tmp_path, ai_local_base_url="http://localhost:11434/v1")

        assert configured.base_url_for(TASK_PRIMARY_VERDICT_LOCAL) == (
            "http://localhost:11434/v1"
        )

    def test_the_local_rung_goes_to_the_local_adapter_not_the_hosted_one(self, tmp_path):
        hosted = FakeProvider(VERDICT)
        local = FakeProvider(VERDICT, model_id="local/fake")
        configured = settings(tmp_path, ai_local_base_url="http://localhost:11434/v1")
        subject = ConfiguredAIClient(
            hosted,
            settings=configured,
            cache=VerdictCache(tmp_path / "cache", enabled=False),
            local_provider=local,
        )

        result = subject.complete(task=TASK_PRIMARY_VERDICT_LOCAL, prompt="p", schema={})

        assert result.model_id == "local/fake"
        assert hosted.call_count == 0
        assert local.call_count == 1

    def test_with_no_local_runtime_the_rung_says_so_instead_of_asking_the_wrong_url(
        self, tmp_path
    ):
        """`ModelUnavailable` because that is the truth and because the ladder
        already moves past it - so an unconfigured rung costs a run nothing,
        and the message names the setting that would configure it."""

        hosted = FakeProvider(VERDICT)
        subject = client(tmp_path, hosted, ai_local_base_url="")

        with pytest.raises(ModelUnavailable, match="ai_local_base_url"):
            subject.complete(task=TASK_PRIMARY_VERDICT_LOCAL, prompt="p", schema={})
        assert hosted.call_count == 0


class TestModelRegistry:
    """What is known about a model, before it is used."""

    def test_the_default_models_support_strict_schema(self):
        assert capabilities_for("openai/gpt-oss-20b").supports_strict_schema
        assert capabilities_for("qwen/qwen3.8-27b").supports_strict_schema

    def test_a_model_without_strict_support_is_recorded_as_such(self):
        """Recorded so it is not chosen by mistake."""

        assert capabilities_for("llama-3.3-70b-versatile").supports_strict_schema is False
        assert "llama-3.3-70b-versatile" not in strict_schema_models()

    def test_an_unregistered_model_raises(self):
        with pytest.raises(UnknownModelError):
            capabilities_for("some/model-nobody-checked")

    def test_strict_output_from_a_model_that_cannot_guarantee_it_raises(self, tmp_path):
        """Rather than silently downgrading: best-effort errors on a schema
        miss, so the retry logic would be reasoning about the wrong failure."""

        with pytest.raises(StrictSchemaUnsupportedError):
            client(
                tmp_path, ai_reasoner_model="llama-3.3-70b-versatile"
            ).complete(task=TASK_PRIMARY_VERDICT, prompt="p", schema={"type": "object"})

    def test_best_effort_mode_permits_a_model_without_strict_support(self, tmp_path):
        """It has to be chosen deliberately, and then it is allowed."""

        result = client(
            tmp_path,
            ai_reasoner_model="llama-3.3-70b-versatile",
            ai_schema_mode=SCHEMA_MODE_BEST_EFFORT,
        ).complete(task=TASK_PRIMARY_VERDICT, prompt="p", schema={"type": "object"})

        assert result.schema_mode == SCHEMA_MODE_BEST_EFFORT


class TestDeterminismControls:
    """Everything available, and no claim beyond it."""

    def test_temperature_zero_and_a_seed_are_sent_on_every_call(self, tmp_path):
        """Neither was available on the API the research assumed."""

        provider = FakeProvider(VERDICT)

        client(tmp_path, provider).complete(
            task=TASK_PRIMARY_VERDICT, prompt="p", schema={"type": "object"}
        )

        assert provider.calls[0]["temperature"] == 0.0
        assert provider.calls[0]["seed"] == 42

    def test_strict_schema_is_requested_by_default(self, tmp_path):
        provider = FakeProvider(VERDICT)

        client(tmp_path, provider).complete(
            task=TASK_PRIMARY_VERDICT, prompt="p", schema={"type": "object"}
        )

        assert provider.schemas_were_strict()

    def test_the_result_records_the_model_the_provider_reported(self, tmp_path):
        """Not the model that was requested: a provider can serve a different
        build under the same name."""

        provider = FakeProvider(VERDICT, model_id="fake/actually-served-this")

        result = client(tmp_path, provider).complete(
            task=TASK_PRIMARY_VERDICT, prompt="p", schema={"type": "object"}
        )

        assert result.model_id == "fake/actually-served-this"

    def test_every_result_carries_what_is_needed_to_reproduce_it(self, tmp_path):
        result = client(tmp_path).complete(
            task=TASK_PRIMARY_VERDICT,
            prompt="p",
            schema={"type": "object"},
            prompt_version="primary_verdict.v1",
            evidence_hash="abc",
        )

        assert result.task == TASK_PRIMARY_VERDICT
        assert result.prompt_version == "primary_verdict.v1"
        assert result.schema_mode == SCHEMA_MODE_STRICT
        assert result.model_id


class TestWhatTheCacheKeyHolds:
    """Everything that could change the answer, so a hit is only ever a hit
    on the identical question."""

    def test_the_decoding_effort_changes_the_key(self):
        """It changes the answer: measured on one verdict, `low` spent 85
        completion tokens where the default spent 223. Leaving it out of the
        key meant a run at one effort could be served an answer produced at
        another."""

        base = dict(
            task=TASK_PRIMARY_VERDICT,
            prompt_version="primary_verdict@1",
            model_id="openai/gpt-oss-20b",
            schema_mode=SCHEMA_MODE_STRICT,
            evidence_hash="ev",
        )

        assert VerdictCache.key(**base, reasoning_effort="low") != VerdictCache.key(
            **base, reasoning_effort="high"
        )
        assert VerdictCache.key(**base, reasoning_effort="low") == VerdictCache.key(
            **base, reasoning_effort="low"
        )


class TestVerdictCache:
    """One mechanism, four problems."""

    def test_an_identical_question_is_answered_without_calling_the_provider(self, tmp_path):
        provider = FakeProvider(VERDICT)
        subject = client(tmp_path, provider)

        first = subject.complete(
            task=TASK_PRIMARY_VERDICT,
            prompt="p",
            schema={"type": "object"},
            prompt_version="v1",
            evidence_hash="abc",
        )
        second = subject.complete(
            task=TASK_PRIMARY_VERDICT,
            prompt="p",
            schema={"type": "object"},
            prompt_version="v1",
            evidence_hash="abc",
        )

        assert provider.call_count == 1
        assert first.cached is False
        assert second.cached is True
        assert second.content == first.content

    @pytest.mark.parametrize(
        "field,value",
        [
            ("prompt_version", "v2"),
            ("evidence_hash", "different"),
        ],
    )
    def test_anything_that_could_change_the_answer_misses_the_cache(
        self, tmp_path, field, value
    ):
        """Which is why there is no invalidation logic to get wrong."""

        provider = FakeProvider([VERDICT, VERDICT])
        subject = client(tmp_path, provider)
        arguments = {
            "task": TASK_PRIMARY_VERDICT,
            "prompt": "p",
            "schema": {"type": "object"},
            "prompt_version": "v1",
            "evidence_hash": "abc",
        }

        subject.complete(**arguments)
        subject.complete(**{**arguments, field: value})

        assert provider.call_count == 2

    def test_a_different_task_misses_the_cache(self, tmp_path):
        """The two tasks run on different models, so sharing an entry would
        return one model's answer stamped with the other's name."""

        provider = FakeProvider([VERDICT, VERDICT])
        subject = client(tmp_path, provider)

        subject.complete(task=TASK_PRIMARY_VERDICT, prompt="p", schema={}, evidence_hash="a")
        subject.complete(task=TASK_VERIFICATION, prompt="p", schema={}, evidence_hash="a")

        assert provider.call_count == 2

    def test_the_key_does_not_depend_on_argument_ordering(self):
        assert VerdictCache.key("t", "v", "m", "s", "e") == VerdictCache.key(
            "t", "v", "m", "s", "e"
        )
        assert VerdictCache.key("t", "v", "m", "s", "e") != VerdictCache.key(
            "v", "t", "m", "s", "e"
        )

    def test_a_cached_entry_survives_a_new_client(self, tmp_path):
        """What makes a warmed cache replay a whole run instantly."""

        first_provider = FakeProvider(VERDICT)
        client(tmp_path, first_provider).complete(
            task=TASK_PRIMARY_VERDICT, prompt="p", schema={}, evidence_hash="abc"
        )

        second_provider = FakeProvider(VERDICT)
        result = client(tmp_path, second_provider).complete(
            task=TASK_PRIMARY_VERDICT, prompt="p", schema={}, evidence_hash="abc"
        )

        assert result.cached is True
        assert second_provider.call_count == 0

    def test_a_corrupt_cache_entry_is_a_miss_rather_than_a_failure(self, tmp_path):
        """A run dying because a cache file was truncated would be worse than
        paying for the call again."""

        cache = VerdictCache(tmp_path / "cache")
        key = VerdictCache.key("t", "v", "m", "s", "e")
        cache.put(key, {"content": {}, "model_id": "m"})
        (tmp_path / "cache" / f"{key}.json").write_text("{ truncated", encoding="utf-8")

        assert VerdictCache(tmp_path / "cache").get(key) is None

    def test_a_disabled_cache_calls_the_provider_every_time(self, tmp_path):
        provider = FakeProvider([VERDICT, VERDICT])
        subject = client(tmp_path, provider, ai_cache_enabled=False)

        subject.complete(task=TASK_PRIMARY_VERDICT, prompt="p", schema={}, evidence_hash="a")
        subject.complete(task=TASK_PRIMARY_VERDICT, prompt="p", schema={}, evidence_hash="a")

        assert provider.call_count == 2

    def test_a_cache_entry_records_what_produced_it(self, tmp_path):
        """So an entry can be inspected by hand while the pipeline is built."""

        client(tmp_path).complete(
            task=TASK_PRIMARY_VERDICT,
            prompt="p",
            schema={},
            prompt_version="v1",
            evidence_hash="abc",
        )

        entry = json.loads(
            next((tmp_path / "cache").glob("*.json")).read_text(encoding="utf-8")
        )
        assert entry["task"] == TASK_PRIMARY_VERDICT
        assert entry["prompt_version"] == "v1"
        assert entry["evidence_hash"] == "abc"
        assert entry["schema_mode"] == SCHEMA_MODE_STRICT


class TestStrictify:
    """Turning an ordinary schema into one constrained decoding accepts."""

    def test_every_property_becomes_required(self):
        result = strictify(
            {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "integer"}}}
        )

        assert result["required"] == ["a", "b"]

    def test_additional_properties_are_forbidden(self):
        result = strictify({"type": "object", "properties": {"a": {"type": "string"}}})

        assert result["additionalProperties"] is False

    def test_nested_objects_are_rewritten_too(self):
        result = strictify(
            {
                "type": "object",
                "properties": {
                    "inner": {"type": "object", "properties": {"x": {"type": "string"}}}
                },
            }
        )

        assert result["properties"]["inner"]["additionalProperties"] is False
        assert result["properties"]["inner"]["required"] == ["x"]

    def test_array_items_are_rewritten(self):
        result = strictify(
            {
                "type": "array",
                "items": {"type": "object", "properties": {"ref": {"type": "string"}}},
            }
        )

        assert result["items"]["required"] == ["ref"]

    def test_a_schema_with_no_properties_is_left_alone(self):
        assert strictify({"type": "string"}) == {"type": "string"}


class TestOpenAICompatibleProvider:
    """One POST, and what happens when it goes wrong."""

    def transport(self, handler) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler))

    def ok_response(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "openai/gpt-oss-20b",
                "choices": [{"message": {"content": json.dumps(VERDICT)}}],
                "usage": {"total_tokens": 42},
            },
        )

    def test_a_successful_call_returns_parsed_content(self):
        provider = OpenAICompatibleProvider(
            "https://example.test/v1", "k", client=self.transport(self.ok_response)
        )

        result = provider.complete("openai/gpt-oss-20b", "p", {"type": "object"})

        assert result["content"] == VERDICT
        assert result["model_id"] == "openai/gpt-oss-20b"

    def test_the_request_carries_the_strict_schema_and_the_seed(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return self.ok_response(request)

        OpenAICompatibleProvider(
            "https://example.test/v1", "k", client=self.transport(handler)
        ).complete("openai/gpt-oss-20b", "p", {"type": "object", "properties": {"a": {}}})

        assert captured["response_format"]["json_schema"]["strict"] is True
        assert captured["response_format"]["json_schema"]["schema"]["required"] == ["a"]
        assert captured["temperature"] == 0.0
        assert captured["seed"] == 42

    def test_a_missing_api_key_is_refused_before_any_request(self):
        provider = OpenAICompatibleProvider("https://example.test/v1", "")

        with pytest.raises(ProviderError, match="never in a settings default"):
            provider.complete("openai/gpt-oss-20b", "p", {})

    def test_a_rate_limit_that_never_clears_is_reported_as_one(self):
        """Waited out a bounded number of times, then reported.

        Bounded because an unbounded wait is a hung demonstration, and
        reported rather than swallowed because the caller above has to be
        able to tell this apart from a model that answered badly.
        """

        waits = []
        provider = OpenAICompatibleProvider(
            "https://example.test/v1",
            "k",
            client=self.transport(lambda request: httpx.Response(429, text="slow down")),
            sleep=waits.append,
        )

        with pytest.raises(ProviderRateLimited, match="tokens per minute"):
            provider.complete("openai/gpt-oss-20b", "p", {})

        assert len(waits) == MAX_RATE_LIMIT_WAITS

    def test_a_rate_limit_is_waited_out_rather_than_failing_the_rung(self):
        """The fix for four facts in fifteen being decided by the table.

        A tokens-per-minute cap is the one refusal the provider tells us is
        temporary. Translated into `ModelUnavailable` it reads to the ladder
        as an outage, so the reasoner descends to a model with a *lower*
        limit and then to the arbiter - and the run looks successful while
        having quietly stopped using the models it is configured with.
        """

        waits = []
        answers = iter([429, 429, 200])

        def handler(request: httpx.Request) -> httpx.Response:
            status = next(answers)
            if status == 429:
                return httpx.Response(429, headers={"retry-after": "7"})
            return self.ok_response(request)

        provider = OpenAICompatibleProvider(
            "https://example.test/v1", "k",
            client=self.transport(handler), sleep=waits.append,
        )

        answer = provider.complete("openai/gpt-oss-20b", "p", {})

        assert answer["content"] == VERDICT
        assert waits == [7.0, 7.0]

    def test_an_unreadable_retry_after_still_waits_long_enough_to_help(self):
        """The header is preferred because the provider knows when the window
        rolls over. Absent, a per-minute window needs more than a moment."""

        waits = []
        provider = OpenAICompatibleProvider(
            "https://example.test/v1",
            "k",
            client=self.transport(lambda request: httpx.Response(429)),
            sleep=waits.append,
        )

        with pytest.raises(ProviderRateLimited):
            provider.complete("openai/gpt-oss-20b", "p", {})

        assert waits == [FALLBACK_WAIT_SECONDS] * MAX_RATE_LIMIT_WAITS

    def test_an_absurd_retry_after_cannot_stall_a_run(self):
        waits = []
        provider = OpenAICompatibleProvider(
            "https://example.test/v1",
            "k",
            client=self.transport(
                lambda request: httpx.Response(429, headers={"retry-after": "9000"})
            ),
            sleep=waits.append,
        )

        with pytest.raises(ProviderRateLimited):
            provider.complete("openai/gpt-oss-20b", "p", {})

        assert set(waits) == {MAX_WAIT_SECONDS}

    def test_the_budget_is_waited_for_before_a_refusal_is_earned(self):
        """Asking and being refused is not free.

        A burst against a tokens-per-minute cap spends a request out of the
        daily allowance for every refusal. A measured burst of seventeen was
        refused eleven times - eleven requests that bought nothing but a
        `retry-after` header. The budget is reported on every response, so
        the wait happens before the request rather than after it.
        """

        waits = []
        # The fixture reports 42-token calls, so the middle budget is
        # deliberately below one call rather than merely small.
        budget = iter(["4000", "20", "4000"])

        def handler(request: httpx.Request) -> httpx.Response:
            response = self.ok_response(request)
            response.headers["x-ratelimit-remaining-tokens"] = next(budget)
            response.headers["x-ratelimit-reset-tokens"] = "3.5s"
            return response

        provider = OpenAICompatibleProvider(
            "https://example.test/v1", "k",
            client=self.transport(handler), sleep=waits.append,
        )

        provider.complete("openai/gpt-oss-20b", "p", {})
        assert waits == [], "a budget that covers the call is not waited for"

        provider.complete("openai/gpt-oss-20b", "p", {})
        third = provider.complete("openai/gpt-oss-20b", "p", {})

        assert waits == [3.5], "a budget below one call's cost waits first"
        assert third["waited_seconds"] == 3.5

    def test_waiting_is_reported_apart_from_answering(self):
        """A four-second call is usually half a second of model and three and
        a half of waiting. One number cannot say which, and reporting the sum
        as latency makes a fast model look slow."""

        waits = []
        answers = iter([429, 200])

        def handler(request: httpx.Request) -> httpx.Response:
            if next(answers) == 429:
                return httpx.Response(429, headers={"retry-after": "2"})
            return self.ok_response(request)

        provider = OpenAICompatibleProvider(
            "https://example.test/v1", "k",
            client=self.transport(handler), sleep=waits.append,
        )

        answer = provider.complete("openai/gpt-oss-20b", "p", {})

        assert answer["waited_seconds"] == 2.0

    def test_the_reset_header_is_parsed_as_a_duration(self):
        """The provider writes it as `547ms` or `1m6.2s`, not as a number."""

        from app.infrastructure.ai.providers.openai_compatible import _seconds

        assert _seconds("547ms") == pytest.approx(0.547)
        assert _seconds("3.5s") == pytest.approx(3.5)
        assert _seconds("1m6.2s") == pytest.approx(66.2)
        assert _seconds("nonsense") == 0.0
        assert _seconds(None) == 0.0

    def test_the_reasoning_effort_reaches_the_request(self):
        """Tokens are the binding constraint on a per-minute tier, and the
        reasoning a model emits before its answer is tokens."""

        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return self.ok_response(request)

        OpenAICompatibleProvider(
            "https://example.test/v1", "k", client=self.transport(handler)
        ).complete("openai/gpt-oss-20b", "p", {}, reasoning_effort="low")

        assert captured["reasoning_effort"] == "low"

    def test_no_reasoning_effort_leaves_the_providers_default(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return self.ok_response(request)

        OpenAICompatibleProvider(
            "https://example.test/v1", "k", client=self.transport(handler)
        ).complete("openai/gpt-oss-20b", "p", {})

        assert "reasoning_effort" not in captured

    def test_giving_up_still_reports_what_the_waiting_cost(self):
        """A call that waited a minute and then gave up reported `waited: 0`,
        so the transcript showed a seventy-second model where there was a
        seventy-second queue - the exact confusion this accounting exists to
        end, surviving on the one path that returns no body."""

        waits = []
        provider = OpenAICompatibleProvider(
            "https://example.test/v1",
            "k",
            client=self.transport(
                lambda request: httpx.Response(429, headers={"retry-after": "9"})
            ),
            sleep=waits.append,
        )

        with pytest.raises(ProviderRateLimited) as refused:
            provider.complete("openai/gpt-oss-20b", "p", {})

        assert refused.value.waited_seconds == sum(waits)
        assert "totalling 27s" in str(refused.value)

    def test_the_wait_covers_the_shortfall_not_the_whole_window(self):
        """`x-ratelimit-reset-tokens` is when the bucket is *full* again.

        Waiting that long for the few hundred tokens one call is short of is
        the difference between a four-minute release and a twelve-minute one.
        The bucket refills continuously, so the wait is the shortfall divided
        by the rate.
        """

        waits = []
        budget = iter(["8000", "500", "8000"])

        def handler(request: httpx.Request) -> httpx.Response:
            response = self.ok_response(request)
            response.headers["x-ratelimit-limit-tokens"] = "6000"
            response.headers["x-ratelimit-remaining-tokens"] = next(budget)
            response.headers["x-ratelimit-reset-tokens"] = "55s"
            return response

        provider = OpenAICompatibleProvider(
            "https://example.test/v1", "k",
            client=self.transport(handler), sleep=waits.append,
        )

        for _ in range(3):
            provider.complete("openai/gpt-oss-20b", "p", {})

        # The fixture reports 42-token calls. 500 left covers one, so nothing
        # waits; the shortfall path is exercised by the budgets above it.
        assert waits == [], "500 remaining covers a 42-token call"

    def test_a_shortfall_waits_only_long_enough_to_cover_it(self):
        waits = []

        def handler(request: httpx.Request) -> httpx.Response:
            response = httpx.Response(
                200,
                json={
                    "model": "openai/gpt-oss-20b",
                    "choices": [{"message": {"content": json.dumps(VERDICT)}}],
                    "usage": {"total_tokens": 1200},
                },
            )
            response.headers["x-ratelimit-limit-tokens"] = "6000"
            response.headers["x-ratelimit-remaining-tokens"] = "600"
            response.headers["x-ratelimit-reset-tokens"] = "55s"
            return response

        provider = OpenAICompatibleProvider(
            "https://example.test/v1", "k",
            client=self.transport(handler), sleep=waits.append,
        )

        provider.complete("openai/gpt-oss-20b", "p", {})
        provider.complete("openai/gpt-oss-20b", "p", {})

        # 1200 needed, 600 left, refilling at 100/s: six seconds, not 55.
        assert waits == [pytest.approx(6.0)]

    def test_each_model_is_paced_against_its_own_budget(self):
        """One adapter serves every task and the models have separate
        buckets. A single figure paced the verifier against the reasoner's
        healthy budget, so it never waited and earned a refusal instead."""

        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            model = json.loads(request.content)["model"]
            seen.append(model)
            response = self.ok_response(request)
            response.headers["x-ratelimit-limit-tokens"] = "6000"
            # The verifier is empty; the reasoner is full.
            response.headers["x-ratelimit-remaining-tokens"] = (
                "0" if "qwen" in model else "6000"
            )
            response.headers["x-ratelimit-reset-tokens"] = "30s"
            return response

        waits = []
        provider = OpenAICompatibleProvider(
            "https://example.test/v1", "k",
            client=self.transport(handler), sleep=waits.append,
        )

        provider.complete("qwen/qwen3.8-27b", "p", {})
        provider.complete("openai/gpt-oss-20b", "p", {})
        assert waits == [], "neither has been seen twice yet"

        provider.complete("openai/gpt-oss-20b", "p", {})
        assert waits == [], "the reasoner has budget and must not wait"

        provider.complete("qwen/qwen3.8-27b", "p", {})
        assert waits, "the verifier had none left and must wait for its own"

    def test_waiting_can_be_turned_off(self):
        """For a caller that would rather fail now than hold a run open."""

        waits = []
        provider = OpenAICompatibleProvider(
            "https://example.test/v1",
            "k",
            client=self.transport(lambda request: httpx.Response(429)),
            wait_out_rate_limits=False,
            sleep=waits.append,
        )

        with pytest.raises(ProviderRateLimited):
            provider.complete("openai/gpt-oss-20b", "p", {})

        assert waits == []

    def test_an_error_body_is_surfaced_because_it_names_the_refused_field(self):
        provider = OpenAICompatibleProvider(
            "https://example.test/v1",
            "k",
            client=self.transport(
                lambda request: httpx.Response(400, text="schema.properties.x is invalid")
            ),
        )

        with pytest.raises(ProviderError, match="schema.properties.x"):
            provider.complete("openai/gpt-oss-20b", "p", {})

    def test_content_that_is_not_json_is_reported_rather_than_repaired(self):
        provider = OpenAICompatibleProvider(
            "https://example.test/v1",
            "k",
            client=self.transport(
                lambda request: httpx.Response(
                    200, json={"choices": [{"message": {"content": "not json at all"}}]}
                )
            ),
        )

        with pytest.raises(ProviderError, match="not valid JSON"):
            provider.complete("openai/gpt-oss-20b", "p", {})

    def test_a_response_with_no_message_is_reported(self):
        provider = OpenAICompatibleProvider(
            "https://example.test/v1",
            "k",
            client=self.transport(lambda request: httpx.Response(200, json={"choices": []})),
        )

        with pytest.raises(ProviderError, match="no message content"):
            provider.complete("openai/gpt-oss-20b", "p", {})


class TestFakeProvider:
    """The provider every test uses."""

    def test_it_counts_its_calls(self, tmp_path):
        """Which is what lets a test assert the model was never called."""

        provider = FakeProvider(VERDICT)
        subject = client(tmp_path, provider)

        assert provider.call_count == 0
        subject.complete(task=TASK_PRIMARY_VERDICT, prompt="p", schema={})
        assert provider.call_count == 1

    def test_scripted_responses_are_returned_in_order(self):
        provider = FakeProvider([{"n": 1}, {"n": 2}])

        assert provider.complete("m", "p", {})["content"] == {"n": 1}
        assert provider.complete("m", "p", {})["content"] == {"n": 2}

    def test_running_out_of_scripted_responses_fails_loudly(self):
        provider = FakeProvider([{"n": 1}])
        provider.complete("m", "p", {})

        with pytest.raises(ProviderError, match="ran out of scripted responses"):
            provider.complete("m", "p", {})

    def test_it_can_be_told_to_fail_so_the_retry_path_is_testable(self):
        provider = FakeProvider(VERDICT, fail_times=1)

        with pytest.raises(ProviderError):
            provider.complete("m", "p", {})
        assert provider.complete("m", "p", {})["content"] == VERDICT

    def test_it_can_be_told_to_rate_limit(self):
        provider = FakeProvider(VERDICT, rate_limit_times=1)

        with pytest.raises(ProviderRateLimited):
            provider.complete("m", "p", {})

    def test_the_default_response_is_empty_rather_than_a_plausible_verdict(self):
        """A fake returning something plausible by default makes tests pass
        that should have scripted an answer."""

        assert FakeProvider().complete("m", "p", {})["content"] == {}


class TestJsonObjectMode:
    """The third schema mode, for a provider that serves no `json_schema`.

    It exists because `strict` and `best_effort` are not two points on a
    scale: both send `response_format: {"type": "json_schema"}`, so a provider
    that does not serve that shape refuses them equally, and loosening one into
    the other changes nothing. What this mode gives up is the guarantee, and
    these tests are mostly about what replaces it.
    """

    SCHEMA = {
        "type": "object",
        "required": ["verdict", "cited_evidence_refs"],
        "properties": {
            "verdict": {"type": "string"},
            "cited_evidence_refs": {"type": "array"},
        },
    }

    def transport(self, handler) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler))

    def answering(self, content: dict):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "model": "deepseek-chat",
                    "choices": [{"message": {"content": json.dumps(content)}}],
                    "usage": {"total_tokens": 11},
                },
            )

        return handler

    def captured_request(self, schema_mode: str) -> dict:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return self.answering(VERDICT)(request)

        OpenAICompatibleProvider(
            "https://example.test/v1", "k", client=self.transport(handler)
        ).complete("deepseek-chat", "Judge this.", self.SCHEMA, schema_mode)
        return captured

    def test_the_request_asks_for_a_json_object_and_names_no_schema(self):
        """The whole point: a provider that rejects `json_schema` is sent a
        shape it serves, rather than a tightened version of one it does not."""

        captured = self.captured_request(SCHEMA_MODE_JSON_OBJECT)

        assert captured["response_format"] == {"type": "json_object"}

    def test_the_schema_travels_in_the_prompt_instead(self):
        """Carried there because nothing else carries it. The word *json* is
        in the instruction too - providers serving this mode document that it
        has to be, and a prompt without it returns prose."""

        prompt = self.captured_request(SCHEMA_MODE_JSON_OBJECT)["messages"][0]["content"]

        assert prompt.startswith("Judge this.")
        assert "json" in prompt
        assert "cited_evidence_refs" in prompt

    def test_the_prompt_is_untouched_in_every_other_mode(self):
        """A schema appended to a prompt that already constrains the decoder
        is tokens spent saying the same thing twice."""

        for mode in (SCHEMA_MODE_STRICT, SCHEMA_MODE_BEST_EFFORT):
            prompt = self.captured_request(mode)["messages"][0]["content"]
            assert prompt == "Judge this."

    def test_an_answer_missing_a_required_field_is_a_content_error(self):
        """Nothing constrained the decoder, so this is the only check there
        is - and it has to fail loudly, because a verdict with its citation
        missing reads exactly like a verdict that cited nothing deliberately."""

        provider = OpenAICompatibleProvider(
            "https://example.test/v1",
            "k",
            client=self.transport(self.answering({"verdict": "confirms"})),
        )

        with pytest.raises(ProviderContentError) as refused:
            provider.complete("deepseek-chat", "p", self.SCHEMA, SCHEMA_MODE_JSON_OBJECT)

        assert "cited_evidence_refs" in str(refused.value)

    def test_a_complete_answer_is_returned_unchanged(self):
        provider = OpenAICompatibleProvider(
            "https://example.test/v1",
            "k",
            client=self.transport(self.answering(VERDICT)),
        )

        result = provider.complete(
            "deepseek-chat", "p", self.SCHEMA, SCHEMA_MODE_JSON_OBJECT
        )

        assert result["content"] == VERDICT
        assert result["model_id"] == "deepseek-chat"

    def test_the_shape_check_does_not_run_in_the_constrained_modes(self):
        """There it would be a second opinion about a guarantee the decoder
        has already given, and the first disagreement would be unexplainable."""

        provider = OpenAICompatibleProvider(
            "https://example.test/v1",
            "k",
            client=self.transport(self.answering({"verdict": "confirms"})),
        )

        result = provider.complete("deepseek-chat", "p", self.SCHEMA, SCHEMA_MODE_STRICT)

        assert result["content"] == {"verdict": "confirms"}

    def test_the_mode_separates_cached_answers(self):
        """An answer a decoder guaranteed and an answer a prompt asked for are
        not the same answer, so one must never be replayed as the other."""

        constrained = VerdictCache.key(
            TASK_PRIMARY_VERDICT, "v1", "deepseek-chat", SCHEMA_MODE_STRICT, "e", ""
        )
        asked = VerdictCache.key(
            TASK_PRIMARY_VERDICT, "v1", "deepseek-chat", SCHEMA_MODE_JSON_OBJECT, "e", ""
        )

        assert constrained != asked

    def test_a_run_in_this_mode_records_it(self, tmp_path):
        result = client(
            tmp_path,
            ai_reasoner_model="deepseek-chat",
            ai_schema_mode=SCHEMA_MODE_JSON_OBJECT,
        ).complete(task=TASK_PRIMARY_VERDICT, prompt="p", schema=self.SCHEMA)

        assert result.schema_mode == SCHEMA_MODE_JSON_OBJECT


class TestTheDeepSeekModels:
    """Registered so the provider is a configuration change, not a code one."""

    def test_they_are_registered_and_declare_no_strict_schema_support(self):
        """Their API documents `json_object` and does not list `json_schema`.
        Recorded here so it is read off the registry rather than found out
        from a 400 in the middle of a demonstration."""

        for model_id in ("deepseek-chat", "deepseek-reasoner", "deepseek-flash"):
            assert capabilities_for(model_id).supports_strict_schema is False
            assert model_id not in strict_schema_models()

    def test_strict_mode_on_one_of_them_is_refused_by_name(self, tmp_path):
        """Before the request, and naming the model. The alternative is a
        provider error about a field, which reads like a prompt problem."""

        with pytest.raises(StrictSchemaUnsupportedError):
            client(tmp_path, ai_reasoner_model="deepseek-chat").complete(
                task=TASK_PRIMARY_VERDICT, prompt="p", schema={"type": "object"}
            )

    def test_they_are_not_recorded_as_a_free_tier(self):
        """The throughput plan turns on which models cost nothing, and this
        provider is cheap rather than free."""

        assert capabilities_for("deepseek-chat").free_tier is False


class TestTheSchemaModeIsValidated:
    """A typo used to mean *not strict*, which is the quietest way there is to
    lose the one guarantee the design rests on."""

    def test_an_unknown_mode_is_refused_with_the_known_ones_named(self, tmp_path):
        with pytest.raises(ValidationError) as refused:
            settings(tmp_path, ai_schema_mode="json-object")

        assert "json_object" in str(refused.value)

    def test_each_known_mode_is_accepted(self, tmp_path):
        for mode in SCHEMA_MODES:
            assert settings(tmp_path, ai_schema_mode=mode).ai_schema_mode == mode


class TestTheVerifierAtItsOwnProvider:
    """Two judges at two providers, which is what the second opinion needs.

    Two models from one provider share a tokenizer, a serving stack and
    usually a lineage, so they share blind spots - and the verifier exists to
    catch the reasoner being confidently wrong. Until this existed, one URL
    served every task and "a different model" was as far apart as the two
    judges could be.
    """

    def test_unset_sends_the_verifier_where_everything_else_goes(self, tmp_path):
        """The single-provider configuration, and still a correct one."""

        configured = settings(tmp_path)

        assert configured.base_url_for(TASK_VERIFICATION) == configured.ai_base_url
        assert configured.api_key_for(TASK_VERIFICATION) == configured.ai_api_key

    def test_set_sends_only_the_verifier_elsewhere(self, tmp_path):
        configured = settings(
            tmp_path,
            ai_base_url="https://reasoner.test/v1",
            ai_verifier_base_url="https://verifier.test/v1",
            ai_verifier_api_key="verifier-key",
        )

        assert configured.base_url_for(TASK_PRIMARY_VERDICT) == "https://reasoner.test/v1"
        assert configured.base_url_for(TASK_VERIFICATION) == "https://verifier.test/v1"
        assert configured.api_key_for(TASK_PRIMARY_VERDICT) == "test-key"
        assert configured.api_key_for(TASK_VERIFICATION) == "verifier-key"

    def test_a_second_endpoint_on_the_same_host_inherits_the_key(self, tmp_path):
        """Two paths at one provider is a real arrangement - a gateway, a
        second route - and it should not need the key written twice."""

        configured = settings(
            tmp_path,
            ai_base_url="https://one.test/v1",
            ai_verifier_base_url="https://one.test/beta",
        )

        assert configured.api_key_for(TASK_VERIFICATION) == "test-key"

    def test_a_second_provider_with_no_key_of_its_own_gets_none(self, tmp_path):
        """Sending one provider's key to another is a 401, which the ladder
        reads as an outage - so every verdict would publish
        `unverified_unavailable` and the run would look exactly like one whose
        verifier was down. Refusing before the request says which setting is
        missing instead."""

        configured = settings(
            tmp_path,
            ai_base_url="https://api.deepseek.com/v1",
            ai_verifier_base_url="https://api.groq.com/openai/v1",
        )

        assert configured.api_key_for(TASK_VERIFICATION) == ""
        assert configured.api_key_for(TASK_PRIMARY_VERDICT) == "test-key"

    def test_the_verification_call_goes_to_the_second_adapter(self, tmp_path):
        """The point of the whole thing: the verdict and the challenge are
        answered by two different processes at two different companies."""

        reasoner = FakeProvider(VERDICT)
        verifier = FakeProvider(VERDICT, model_id="other/verifier-1")
        configuration = settings(tmp_path)
        client = ConfiguredAIClient(
            reasoner,
            settings=configuration,
            cache=VerdictCache(configuration.ai_cache_directory, False),
            verifier_provider=verifier,
        )

        client.complete(task=TASK_PRIMARY_VERDICT, prompt="p", schema={"type": "object"})
        client.complete(task=TASK_VERIFICATION, prompt="p", schema={"type": "object"})

        assert reasoner.call_count == 1
        assert verifier.call_count == 1

    def test_without_a_second_adapter_everything_goes_to_the_first(self, tmp_path):
        reasoner = FakeProvider(VERDICT)
        configuration = settings(tmp_path)
        client = ConfiguredAIClient(
            reasoner,
            settings=configuration,
            cache=VerdictCache(configuration.ai_cache_directory, False),
        )

        client.complete(task=TASK_PRIMARY_VERDICT, prompt="p", schema={"type": "object"})
        client.complete(task=TASK_VERIFICATION, prompt="p", schema={"type": "object"})

        assert reasoner.call_count == 2

    def test_the_local_rung_is_still_its_own_adapter(self, tmp_path):
        """Three endpoints now, and the one added must not have taken the
        offline rung's place in the lookup."""

        reasoner = FakeProvider(VERDICT)
        verifier = FakeProvider(VERDICT)
        local = FakeProvider(VERDICT)
        configuration = settings(tmp_path, ai_local_base_url="http://localhost:11434/v1")
        client = ConfiguredAIClient(
            reasoner,
            settings=configuration,
            cache=VerdictCache(configuration.ai_cache_directory, False),
            local_provider=local,
            verifier_provider=verifier,
        )

        client.complete(
            task=TASK_PRIMARY_VERDICT_LOCAL, prompt="p", schema={"type": "object"}
        )

        assert local.call_count == 1
        assert reasoner.call_count == 0
        assert verifier.call_count == 0


class TestWhatSurvivesAFanOut:
    """The two things a run must be able to prove about itself, in a worker.

    Both live in context variables rather than thread-locals, and that is the
    whole reason a release can judge its facts concurrently. As thread-locals
    the transcript would omit every call a worker made, and a cold run would
    quietly replay on every worker while reporting itself live - which is the
    one failure this component cannot ship, because its claim is that a model
    having answered is checkable.
    """

    def test_a_capture_reaches_a_worker_thread(self):
        log = CallLog()

        def record_one():
            log.record(
                task=TASK_PRIMARY_VERDICT,
                requested_model="m",
                answered_model="m",
                prompt="p",
                prompt_version="v1",
                schema_mode=SCHEMA_MODE_STRICT,
                evidence_hash="e",
                outcome="answered",
                latency_ms=1,
            )

        with log.capture() as recorded:
            with ThreadPoolExecutor(max_workers=4) as pool:
                for future in [
                    pool.submit(copy_context().run, record_one) for _ in range(8)
                ]:
                    future.result()

        assert len(recorded) == 8

    def test_a_worker_without_the_context_records_nothing(self):
        """The failure the copy prevents, pinned so it cannot come back
        silently: a plain pool thread inherits no capture at all."""

        log = CallLog()

        def record_one():
            log.record(
                task=TASK_PRIMARY_VERDICT,
                requested_model="m",
                answered_model="m",
                prompt="p",
                prompt_version="v1",
                schema_mode=SCHEMA_MODE_STRICT,
                evidence_hash="e",
                outcome="answered",
                latency_ms=1,
            )

        with log.capture() as recorded:
            with ThreadPoolExecutor(max_workers=2) as pool:
                pool.submit(record_one).result()

        assert recorded == []

    def test_the_cold_run_flag_reaches_a_worker_thread(self, tmp_path):
        provider = FakeProvider(VERDICT)
        configuration = settings(tmp_path)
        client = ConfiguredAIClient(
            provider,
            settings=configuration,
            cache=VerdictCache(configuration.ai_cache_directory, True),
        )

        def ask():
            return client.complete(
                task=TASK_PRIMARY_VERDICT, prompt="p", schema={"type": "object"}
            )

        ask()
        warm = provider.call_count

        with client.ignoring_the_cache():
            with ThreadPoolExecutor(max_workers=2) as pool:
                pool.submit(copy_context().run, ask).result()

        assert provider.call_count == warm + 1, "the worker must not replay"
