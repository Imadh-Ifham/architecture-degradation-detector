"""Live model smoke test.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    One real call per configured model, against the real provider, asserting
    only what has to be true before any reasoning is built on top: the endpoint
    answers, the configured model is the one that replies, and a strict schema
    comes back as parseable JSON with no field invented.

    Deselected by default. `pyproject.toml` sets `-m 'not live'`, so the whole
    suite stays runnable with no key and no network - a suite that fails for
    reasons unrelated to the code under test stops being trusted.

    To run it, put a key in `.env` as `ai_api_key` and then:

        uv run pytest -m live -v

    Why this is a test rather than a script. The two things most likely to be
    wrong are the provider's strict-schema support and the model id, and both
    produce a clear failure here instead of a confusing one three
    subcomponents later.
"""

import httpx
import pytest

from app.infrastructure.ai.interface import ConfiguredAIClient
from app.infrastructure.ai.model_configuration import (
    TASK_PRIMARY_VERDICT,
    TASK_VERIFICATION,
    AISettings,
)
from app.infrastructure.ai.providers.openai_compatible import OpenAICompatibleProvider

pytestmark = pytest.mark.live

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["confirms", "contradicts", "insufficient_evidence"],
        },
        "cited": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["verdict", "cited"],
    "additionalProperties": False,
}

PROMPT = (
    "Evidence:\n"
    "  ev:1  network policy: checkoutservice may send egress to paymentservice\n"
    "  ev:2  deployment: checkoutservice sets PAYMENT_SERVICE_ADDR=paymentservice:50051\n\n"
    "Rule: checkoutservice may call paymentservice.\n"
    "Observed: checkoutservice communicates-with paymentservice.\n\n"
    "Does the observation obey the rule? Cite only the evidence references above."
)


@pytest.fixture
def settings() -> AISettings:
    configured = AISettings()
    if not configured.ai_api_key:
        pytest.skip("no ai_api_key in .env - put the key there and re-run")
    return configured


@pytest.fixture
def client(settings: AISettings) -> ConfiguredAIClient:
    provider = OpenAICompatibleProvider(
        base_url=settings.ai_base_url,
        api_key=settings.ai_api_key,
        timeout_seconds=settings.ai_timeout_seconds,
    )
    # Caching off: a cached answer would make this test pass without a call,
    # which is the one thing it exists to prove.
    return ConfiguredAIClient(provider, settings=settings, cache=_NoCache())


class _NoCache:
    @staticmethod
    def key(*_args) -> str:
        return "live"

    def get(self, _key):
        return None

    def put(self, _key, _entry) -> None:
        return None


def test_the_real_rate_limits_are_reported(settings, capsys):
    """Print this account's actual limits, per configured model.

    A free roster's figures change without notice and every published number
    for them disagrees with every other, so they are read from the account
    rather than believed. This is a test and not a scratch script because the
    checklist asks for it again before demo week, and a script that ran once
    is a number nobody can re-check.

    It talks to `httpx` directly rather than through the adapter, which is the
    one place in the suite that is allowed to: the adapter drops response
    headers on purpose, because no component has any business reading them,
    and what is under test here is the account rather than the code path.
    """

    report = []
    for model in (settings.ai_reasoner_model, settings.ai_verifier_model):
        response = httpx.post(
            f"{settings.ai_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.ai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_completion_tokens": 1,
                "temperature": settings.ai_temperature,
            },
            timeout=settings.ai_timeout_seconds,
        )
        assert response.status_code == 200, response.text[:300]

        limits = {
            name: value
            for name, value in response.headers.items()
            if "ratelimit" in name
        }
        assert limits, "the provider reported no rate-limit headers"
        report.append((model, limits))

    with capsys.disabled():
        print()
        for model, limits in report:
            print(f"  {model}")
            for name in sorted(limits):
                print(f"    {name}: {limits[name]}")


@pytest.mark.parametrize("task", [TASK_PRIMARY_VERDICT, TASK_VERIFICATION])
def test_the_configured_model_answers_under_a_strict_schema(client, settings, task):
    """Both models, because the verifier being wrong is as bad as the reasoner
    being wrong and is far easier to leave untested."""

    result = client.complete(
        task=task,
        prompt=PROMPT,
        schema=VERDICT_SCHEMA,
        prompt_version="smoke-1",
        evidence_hash="smoke",
    )

    assert result.model_id == settings.model_for(task)
    assert result.cached is False

    # Already parsed: the client hands back the response as data, so a test
    # that parsed it again would be testing its own string handling.
    answer = result.content
    assert set(answer) == {"verdict", "cited"}
    assert answer["verdict"] in {"confirms", "contradicts", "insufficient_evidence"}


def test_every_citation_resolves_to_evidence_that_was_supplied(client):
    """The grounding guarantee, measured once against the real model rather
    than assumed. No schema can express this, which is why it is checked in
    plain Python everywhere it matters."""

    result = client.complete(
        task=TASK_PRIMARY_VERDICT,
        prompt=PROMPT,
        schema=VERDICT_SCHEMA,
        prompt_version="smoke-1",
        evidence_hash="smoke",
    )

    supplied = {"ev:1", "ev:2"}
    invented = set(result.content["cited"]) - supplied

    assert not invented, f"the model cited evidence that was never supplied: {invented}"
