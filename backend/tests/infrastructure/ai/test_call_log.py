"""Call log, transcript store and narration tests.

Author: Aman Mohamed M.A
Date: 2026-10-21
Description:
    Covers the three pieces that let a reader check whether a model was
    involved in a run, rather than take the run's word for it.

    The one property worth stating is the one the whole path exists for: a
    keyless run and a working run publish the same verdicts, so a test that
    only asserted on verdicts would pass in both. Every test here asserts on
    the calls instead.

    The fake provider throughout, for the same reason the rest of the suite
    uses it: a test that fails because somebody exhausted a free tier teaches
    nothing.
"""

import pytest

from app.components.architecture_validation.models import PromptTemplate
from app.domain.model_access import ModelUnavailable
from app.infrastructure.ai.call_log import (
    OUTCOME_ANSWERED,
    OUTCOME_REPLAYED,
    OUTCOME_UNAVAILABLE,
    CallLog,
    summarise,
)
from app.infrastructure.ai.interface import ConfiguredAIClient, VerdictCache
from app.infrastructure.ai.model_configuration import (
    TASK_NARRATION,
    TASK_PRIMARY_VERDICT,
    AISettings,
)
from app.infrastructure.ai.providers.fake import FakeProvider
from app.infrastructure.ai.run_narration import (
    MAX_SAMPLED_CALLS,
    NarrationUnavailable,
    RunNarrator,
)
from app.infrastructure.ai.transcript_store import ModelTranscriptFileStore

VERDICT = {"verdict": "confirms", "cited_evidence_refs": ["ev:1"]}

ACCOUNT = {
    "what_it_read": "It read one release and two decisions.",
    "what_it_concluded": "It confirmed thirteen dependencies.",
    "what_to_distrust": "Two models agreeing is not two checks.",
    "headline": "Thirteen confirmed, two contradicted.",
}

SCHEMA = {
    "type": "object",
    "properties": {"verdict": {"type": "string"}},
}


def settings(tmp_path, **overrides) -> AISettings:
    values = {
        "ai_api_key": "test-key",
        "ai_cache_directory": str(tmp_path / "cache"),
        "ai_narrator_model": "openai/gpt-oss-120b",
            # Pinned, not inherited. `AISettings` reads the developer's .env, so
        # leaving this out made three cache tests pass or fail according to a
        # file that is not in the repository - which is the same complaint
        # this module's docstring already makes about keys and rate limits.
        "ai_cache_enabled": True,
    }
    values.update(overrides)
    return AISettings(**values)


def client(tmp_path, log, provider=None) -> ConfiguredAIClient:
    configured = settings(tmp_path)
    return ConfiguredAIClient(
        provider or FakeProvider(VERDICT),
        settings=configured,
        cache=VerdictCache(configured.ai_cache_directory, True),
        call_log=log,
    )


def ask(ai, task=TASK_PRIMARY_VERDICT, evidence_hash="ev-hash"):
    return ai.complete(
        task=task,
        prompt="Does the observation obey the rule?",
        schema=SCHEMA,
        prompt_version="primary_verdict@1",
        evidence_hash=evidence_hash,
    )


class TestWhatTheLogRecords:
    """One row per call, carrying what a reader cannot otherwise see."""

    def test_a_live_call_is_recorded_with_its_request_and_its_answer(self, tmp_path):
        log = CallLog()
        ai = client(tmp_path, log)

        with log.capture() as calls:
            ask(ai)

        assert len(calls) == 1
        assert calls[0].outcome == OUTCOME_ANSWERED
        assert calls[0].prompt == "Does the observation obey the rule?"
        assert calls[0].response == VERDICT

    def test_the_evidence_hash_is_recorded_so_a_call_can_be_found_again(
        self, tmp_path
    ):
        """The other half of the canvas join. A published edge names the
        evidence it was judged from, and this is what makes that name resolve
        to the request and the answer."""

        log = CallLog()
        ai = client(tmp_path, log)

        with log.capture() as calls:
            ask(ai, evidence_hash="package-7f3a")

        assert calls[0].evidence_hash == "package-7f3a"

    def test_the_model_that_answered_is_recorded_beside_the_one_requested(
        self, tmp_path
    ):
        """A provider can serve a different build under the name it was asked
        for, so the two are kept apart rather than assumed equal."""

        log = CallLog()
        ai = client(tmp_path, log, FakeProvider(VERDICT, model_id="fake/other-build"))

        with log.capture() as calls:
            ask(ai)

        assert calls[0].requested_model == "openai/gpt-oss-20b"
        assert calls[0].answered_model == "fake/other-build"

    def test_a_cached_answer_is_recorded_as_a_replay_rather_than_vanishing(
        self, tmp_path
    ):
        """The case that made the original question hard: a warm cache makes a
        real run report no calls, which reads as no model to anyone who was
        not told otherwise."""

        log = CallLog()
        provider = FakeProvider(VERDICT)
        ai = client(tmp_path, log, provider)

        with log.capture() as first:
            ask(ai)
        with log.capture() as second:
            ask(ai)

        assert provider.call_count == 1
        assert first[0].outcome == OUTCOME_ANSWERED
        assert second[0].outcome == OUTCOME_REPLAYED
        assert second[0].response == VERDICT

    def test_a_model_that_could_not_be_reached_is_recorded_with_the_reason(
        self, tmp_path
    ):
        """The sentence the provider gave is the only thing that says why a
        rung went unanswered, and the ladder above keeps the rung and discards
        it."""

        log = CallLog()
        ai = client(tmp_path, log, FakeProvider(VERDICT, fail_times=1))

        with log.capture() as calls:
            with pytest.raises(ModelUnavailable):
                ask(ai)

        assert calls[0].outcome == OUTCOME_UNAVAILABLE
        assert calls[0].response is None
        assert "scripted provider failure" in calls[0].error

    def test_calls_made_before_a_failure_are_still_in_the_list(self, tmp_path):
        """A run that died halfway is exactly when the transcript is worth
        reading, so the list is handed over before the block runs."""

        log = CallLog()
        ai = client(tmp_path, log)

        with pytest.raises(RuntimeError):
            with log.capture() as calls:
                ask(ai)
                raise RuntimeError("the run fell over")

        assert len(calls) == 1


class TestWhenNothingIsCapturing:
    """Outside a block nothing is kept, so a long-lived process stays bounded."""

    def test_a_call_outside_a_capture_block_is_not_collected(self, tmp_path):
        log = CallLog()
        ai = client(tmp_path, log)

        ask(ai, evidence_hash="outside")

        with log.capture() as calls:
            pass

        assert calls == []

    def test_a_client_with_no_log_still_answers(self, tmp_path):
        """Nothing in a run depends on the log, which is what lets a test leave
        it out without changing what the test measures."""

        configured = settings(tmp_path)
        ai = ConfiguredAIClient(
            FakeProvider(VERDICT),
            settings=configured,
            cache=VerdictCache(configured.ai_cache_directory, True),
        )

        assert ask(ai).content == VERDICT


class TestTheSummary:
    """The counts a reader checks before opening any individual call."""

    def test_live_and_replayed_are_counted_apart(self, tmp_path):
        """Neither answers the question alone: live calls prove a model was
        reached on this run, replays prove the answers came from one earlier."""

        log = CallLog()
        ai = client(tmp_path, log)

        with log.capture() as calls:
            ask(ai)
            ask(ai)
            ask(ai, evidence_hash="another")

        counted = summarise(calls)

        assert counted["calls"] == 3
        assert counted["live"] == 2
        assert counted["replayed"] == 1


class TestTheTranscriptStore:
    """What a run sent, kept beside the graph it published."""

    def test_a_written_transcript_is_read_back_whole(self, tmp_path):
        store = ModelTranscriptFileStore(tmp_path)
        document = {
            "run_id": "abc123",
            "repository_id": "shop",
            "release_id": "v1.0.0",
            "calls": [{"sequence": 1, "task": TASK_PRIMARY_VERDICT}],
        }

        store.write(document)

        assert store.read("shop", "v1.0.0") == document

    def test_the_latest_transcript_is_the_one_a_reader_gets(self, tmp_path):
        store = ModelTranscriptFileStore(tmp_path)
        base = {"repository_id": "shop", "release_id": "v1.0.0", "calls": []}

        store.write({**base, "run_id": "first"})
        store.write({**base, "run_id": "second"})

        assert store.read("shop", "v1.0.0")["run_id"] == "second"

    def test_a_release_with_no_transcript_reads_as_absent(self, tmp_path):
        """Different from a run that called nothing, which is itself a
        finding."""

        assert ModelTranscriptFileStore(tmp_path).read("shop", "v1.0.0") is None


class TestTheNarration:
    """A reading of the result, which is never part of it."""

    def narrator(self, tmp_path, provider=None):
        log = CallLog()
        return RunNarrator(
            client(tmp_path, log, provider or FakeProvider(ACCOUNT)),
            _prompt(),
        )

    def test_the_account_carries_the_model_that_wrote_it(self, tmp_path):
        """The point of showing this beside the verdicts is that a reader can
        tell which sentences a model produced."""

        narration = self.narrator(tmp_path).narrate({"run_id": "abc"}, [])

        assert narration.headline == ACCOUNT["headline"]
        assert narration.model_id == "fake/deterministic-1"

    def test_the_figures_reach_the_model_under_the_names_the_screen_uses(
        self, tmp_path
    ):
        """A number the account quotes has to be findable on the screen beside
        it, under the same name."""

        provider = FakeProvider(ACCOUNT)
        self.narrator(tmp_path, provider).narrate(
            {"run_id": "abc", "verdict_buckets": {"confirmed": 13}}, []
        )

        sent = provider.prompts()[0]

        assert "verdict_buckets:" in sent
        assert "confirmed: 13" in sent

    def test_only_a_sample_of_the_calls_is_sent(self, tmp_path):
        """A hundred near-identical requests say nothing a handful does not,
        and one fact's prompt can be longer than everything else together."""

        provider = FakeProvider(ACCOUNT)
        calls = [
            {"sequence": number, "task": "primary_verdict", "prompt": f"ask {number}"}
            for number in range(1, MAX_SAMPLED_CALLS + 4)
        ]

        self.narrator(tmp_path, provider).narrate({"run_id": "abc"}, calls)

        sent = provider.prompts()[0]

        assert f"ask {MAX_SAMPLED_CALLS}" in sent
        assert f"ask {MAX_SAMPLED_CALLS + 1}" not in sent

    def test_no_model_means_no_account_rather_than_a_template(self, tmp_path):
        """Text assembled here would read like the model's at a glance, and the
        one thing this must not do is make that harder to tell."""

        narrator = self.narrator(tmp_path, FakeProvider(ACCOUNT, fail_times=1))

        with pytest.raises(NarrationUnavailable):
            narrator.narrate({"run_id": "abc"}, [])

    def test_the_narrator_asks_for_its_own_task(self, tmp_path):
        """Not one of the judges: a task of its own so nothing it produces is
        mistaken for a verdict, and so it names no model either."""

        assert settings(tmp_path).model_for(TASK_NARRATION) == "openai/gpt-oss-120b"


def _prompt() -> PromptTemplate:
    return PromptTemplate(
        version="run_narrative@1",
        system="You write the account of a decided run.",
        body="Run {{run_id}}.\n\n{{figures}}\n\n{{calls}}",
    )
