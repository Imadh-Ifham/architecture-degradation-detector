"""Fake AI provider.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    A scripted provider for tests.

    Every test in the suite uses this one. The test suite must not depend on a
    network, a key or a free tier's rate limit: a suite that fails because
    somebody else exhausted a quota teaches nothing and gets ignored, which is
    worse than having no test.

    It counts its calls. That is what lets a test assert something the real
    provider cannot be asked - that an uncovered fact reached its bucket
    without the model being called at all.

    It can also be told to misbehave, which is the point of having it rather
    than a stub returning one canned answer. The guards, the retry and the
    rate-limit path are all only testable against a provider that can fail on
    demand.
"""

import json

from .openai_compatible import ProviderError, ProviderRateLimited

DEFAULT_MODEL_ID = "fake/deterministic-1"


class FakeProvider:
    """Returns scripted responses and records what it was asked."""

    def __init__(
        self,
        responses: dict | list | None = None,
        fail_times: int = 0,
        rate_limit_times: int = 0,
        malformed_times: int = 0,
        model_id: str = DEFAULT_MODEL_ID,
    ) -> None:
        """Script the provider.

        `responses` is either one response returned every time, or a list
        consumed in order - a list so a test can script a rejection followed by
        an acceptance, which is the retry path.

        The three failure counters are separate because the behaviours differ:
        a transport failure is retried, a rate limit is not worth retrying
        immediately, and malformed content is the guards' concern rather than
        the provider's.
        """

        self._responses = responses
        self._fail_times = fail_times
        self._rate_limit_times = rate_limit_times
        self._malformed_times = malformed_times
        self._model_id = model_id

        self.calls: list[dict] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def complete(
        self,
        model_id: str,
        prompt: str,
        schema: dict,
        strict: bool = True,
        temperature: float = 0.0,
        seed: int | None = 42,
    ) -> dict:
        """Return the next scripted response, or raise as scripted."""

        self.calls.append(
            {
                "model_id": model_id,
                "prompt": prompt,
                "schema": schema,
                "strict": strict,
                "temperature": temperature,
                "seed": seed,
            }
        )

        if self._rate_limit_times > 0:
            self._rate_limit_times -= 1
            raise ProviderRateLimited("scripted rate limit")

        if self._fail_times > 0:
            self._fail_times -= 1
            raise ProviderError("scripted provider failure")

        if self._malformed_times > 0:
            self._malformed_times -= 1
            raise ProviderError("scripted malformed content: not valid JSON")

        return {
            "content": self._next_response(),
            "model_id": self._model_id,
            "usage": {"total_tokens": len(prompt.split())},
        }

    def _next_response(self):
        if self._responses is None:
            # An empty object rather than an invented verdict. A fake that
            # returns a plausible answer by default makes tests pass that
            # should have scripted one.
            return {}
        if isinstance(self._responses, list):
            if not self._responses:
                raise ProviderError("the fake provider ran out of scripted responses")
            return self._responses.pop(0)
        return self._responses

    def prompts(self) -> list[str]:
        """Every prompt the provider was sent, in order."""

        return [call["prompt"] for call in self.calls]

    def schemas_were_strict(self) -> bool:
        """Whether every call asked for strict schema output."""

        return bool(self.calls) and all(call["strict"] for call in self.calls)

    def as_json(self) -> str:
        """The recorded calls, for a test that needs to inspect them."""

        return json.dumps(self.calls, default=str, indent=2)
