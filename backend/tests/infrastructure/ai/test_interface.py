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

import httpx
import pytest

from app.domain.model_access import ModelUnavailable
from app.infrastructure.ai.interface import (
    ConfiguredAIClient,
    StrictSchemaUnsupportedError,
    VerdictCache,
)
from app.infrastructure.ai.model_configuration import (
    SCHEMA_MODE_BEST_EFFORT,
    SCHEMA_MODE_STRICT,
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
from app.infrastructure.ai.providers.openai_compatible import (
    FALLBACK_WAIT_SECONDS,
    MAX_RATE_LIMIT_WAITS,
    MAX_WAIT_SECONDS,
    OpenAICompatibleProvider,
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
