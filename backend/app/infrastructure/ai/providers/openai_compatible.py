"""OpenAI-compatible provider adapter.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    One HTTP POST to a chat-completions endpoint, for every provider that
    speaks that API - which is all of the hosted and local runtimes under
    consideration.

    A plain HTTP client rather than a vendor SDK, for three reasons. The
    endpoint is one POST with a JSON body, so an SDK's convenience layer would
    sit behind an abstraction that already does the same job. An SDK earns its
    place for streaming, tool loops and multimodal payloads, none of which this
    uses. And a vendor SDK pulls in that vendor's auth, error types and
    defaults, quietly making "swap the provider" harder than changing a URL -
    which is the one property this adapter exists to preserve.

    Schemas are post-processed before they are sent. Constrained decoding
    requires every property to be required and additional properties to be
    forbidden; a schema generated from an ordinary dataclass satisfies neither,
    and the provider rejects it with an error that does not say which part was
    wrong.
"""

import json
import re
import time
from dataclasses import dataclass

import httpx

MAX_RATE_LIMIT_WAITS = 3
FALLBACK_WAIT_SECONDS = 20.0
MAX_WAIT_SECONDS = 60.0

ASSUMED_CALL_TOKENS = 1200
"""What one call is assumed to cost before any have been measured.

Used only to decide whether to pace before the first response has reported a
budget. Deliberately a little high: being early to wait costs a second, and
being late costs a refused request out of a daily allowance.
"""


class ProviderError(RuntimeError):
    """The provider could not produce a usable response."""


class ProviderContentError(ProviderError):
    """The provider answered and the answer could not be read.

    Separate from the other failures because the response to it is different.
    A transport failure is worth trying another model for; content that cannot
    be read is the model's own answer being unusable, and handing the same
    question to a second model would be asking something the first one already
    botched.
    """


class ProviderRateLimited(ProviderError):
    """The provider refused the request for rate reasons.

    Separate from other failures because the response is different: a rate
    limit is worth waiting out, and everything else is worth reporting. On a
    free tier the limit is on tokens per minute, so this fires on a burst of
    large evidence packages rather than on a burst of requests.

    It carries how long was spent waiting before it gave up, because that is
    the whole of the time the call took and none of it was the model.
    """

    def __init__(self, message: str, waited_seconds: float = 0.0) -> None:
        super().__init__(message)
        self.waited_seconds = waited_seconds


def strictify(schema: dict) -> dict:
    """Rewrite a JSON schema into the form constrained decoding accepts.

    Three transformations, applied through the whole tree:
    every property becomes required, additional properties are forbidden, and
    an optional field is expressed as a union with null rather than by being
    absent.

    The last one is the subtle one. Strict mode has no notion of an optional
    property - omitting it from `required` is not allowed - so optionality has
    to move into the type.
    """

    if not isinstance(schema, dict):
        return schema

    result = dict(schema)

    if result.get("type") == "object" or "properties" in result:
        properties = {
            name: strictify(definition)
            for name, definition in (result.get("properties") or {}).items()
        }
        result["properties"] = properties
        # Declaration order, not alphabetical. Sorting is deterministic but
        # it is not the order the caller declared, and a schema whose two
        # field lists disagree about order is a schema no reader can check
        # against the file it came from. It buys nothing from this provider -
        # emission order was measured to be the model's own - so this keeps
        # the request faithful to the declaration rather than relying on it.
        result["required"] = list(properties)
        result["additionalProperties"] = False

    if "items" in result:
        result["items"] = strictify(result["items"])

    for keyword in ("anyOf", "oneOf", "allOf"):
        if keyword in result:
            result[keyword] = [strictify(entry) for entry in result[keyword]]

    return result


@dataclass
class _Budget:
    """One model's token allowance, as the provider last reported it."""

    left: int | None = None
    limit: int = 0
    reset: float = 0.0
    cost: int = ASSUMED_CALL_TOKENS
    """What one call to this model costs, from the last one that answered."""


class OpenAICompatibleProvider:
    """Calls a chat-completions endpoint and returns parsed JSON."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 60.0,
        client: httpx.Client | None = None,
        wait_out_rate_limits: bool = True,
        sleep=time.sleep,
    ) -> None:
        """Bind the adapter to one endpoint.

        `client` is injectable so the request can be exercised against a
        transport stub without a network or a key. `sleep` is injectable for
        the same reason: a test of the waiting path that actually waited
        would be a test nobody runs twice.

        `wait_out_rate_limits` is on by default and it is the difference
        between a run that uses the models and a run that quietly stops
        using them. See `_post`.
        """

        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._client = client
        self._wait_out_rate_limits = wait_out_rate_limits
        self._sleep = sleep
        # Per model, because the budgets are. One adapter serves every task,
        # and the two models a run uses have separate buckets - so a single
        # figure meant the verifier was paced against the reasoner's healthy
        # budget, never waited, and earned a refusal on almost every call.
        self._budget: dict[str, _Budget] = {}

    def complete(
        self,
        model_id: str,
        prompt: str,
        schema: dict,
        strict: bool = True,
        temperature: float = 0.0,
        seed: int | None = 42,
        reasoning_effort: str = "",
    ) -> dict:
        """Send one completion request and return the parsed content.

        `temperature` and `seed` are both set by default. Neither was available
        on the API the research was written against; together they remove the
        avoidable variation. They do not make the call deterministic - batching
        and floating-point reduction order still vary, and a provider can
        redeploy a model under the same name - so the response's own model id
        is recorded rather than assumed.
        """

        if not self._api_key:
            raise ProviderError(
                "No API key configured. Set ai_api_key in .env - never in a settings default."
            )

        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "response_format": self._response_format(schema, strict),
        }
        if seed is not None:
            payload["seed"] = seed
        if reasoning_effort:
            # Tokens are the binding constraint on a per-minute tier, and the
            # reasoning a model emits before its answer is tokens. Measured on
            # a real verdict: low spent 815 total where the default spent
            # 1001, for the same verdict, the same citation and an equivalent
            # sentence. A provider that does not know the field ignores it.
            payload["reasoning_effort"] = reasoning_effort

        response = self._post(payload)
        return self._content(response, model_id)

    def _response_format(self, schema: dict, strict: bool) -> dict:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "response",
                "strict": strict,
                "schema": strictify(schema) if strict else schema,
            },
        }

    def _post(self, payload: dict) -> dict:
        """Send the request, waiting out a rate limit rather than giving up.

        **A rate limit is not a model being unavailable, and treating it as
        one is how a run stops using the models it is configured with.** On a
        tokens-per-minute free tier a burst of evidence packages hits the cap
        within seconds. The caller above translates any provider failure into
        `ModelUnavailable`, so the ladder reads the refusal as an outage,
        descends to the fallback model - which carries a *lower* limit for the
        same work - and then to the arbiter. Four of fifteen facts on one
        recorded run were decided by the deterministic table for no reason
        other than this, and the run looked like a successful one.

        So the one failure the provider tells us is temporary is waited out
        here, where the retry-after header is still readable. Bounded, because
        an unbounded wait is a hung demonstration: three waits, each capped,
        and then it is reported as a rate limit like before.
        """

        waited = 0.0

        model = str(payload.get("model", ""))

        for attempt in range(MAX_RATE_LIMIT_WAITS + 1):
            waited += self._pace(model)
            result = self._send(payload)
            self._remember_budget(model, result)

            if result.status_code != 429:
                break

            if not self._wait_out_rate_limits or attempt == MAX_RATE_LIMIT_WAITS:
                # The waiting is on the error too. A call that waited a
                # minute and then gave up was reporting `waited: 0`, so the
                # transcript showed a seventy-second model where there was a
                # seventy-second queue - the exact confusion this accounting
                # was added to end, surviving on the one path that does not
                # return a body.
                raise ProviderRateLimited(
                    "The provider rate-limited this request and it did not clear "
                    f"after {attempt} wait(s) totalling {waited:.0f}s. On a free "
                    "tier the limit is tokens per minute, so a burst of large "
                    "evidence packages is the usual cause.",
                    waited_seconds=waited,
                )

            wait = _retry_after(result)
            waited += wait
            self._sleep(wait)

        if result.status_code >= 400:
            # The body carries which part of the schema was refused, and
            # without it the error is unactionable.
            raise ProviderError(
                f"The provider returned {result.status_code}: {result.text[:500]}"
            )

        try:
            body = result.json()
        except ValueError as error:
            raise ProviderError("The provider's response was not JSON.") from error

        # Carried out with the body so the caller can tell a slow model from a
        # slow tier. Without it a four-second call looks like the model
        # thinking, when it is three and a half seconds of waiting for a
        # token budget to refill and half a second of answering.
        body["waited_seconds"] = waited
        return body

    def _pace(self, model: str) -> float:
        """Wait before sending when the budget will not cover this call.

        **Asking and being refused is not free.** A burst against a
        tokens-per-minute cap spends a request out of the daily allowance for
        every refusal, and a measured burst of seventeen calls was refused
        eleven times - eleven requests bought nothing but a `retry-after`
        header. Reading the budget the provider already reports and waiting
        first turns those into one planned pause.

        Returns the seconds spent, so the caller can report waiting apart
        from answering.
        """

        budget = self._budget.get(model)
        if not self._wait_out_rate_limits or budget is None or budget.left is None:
            return 0.0

        shortfall = budget.cost - budget.left
        if shortfall <= 0:
            return 0.0

        # Wait for the shortfall to refill, not for the window to reset.
        # `x-ratelimit-reset-tokens` is when the bucket is *full* again, and
        # waiting that long for the few hundred tokens one call is short was
        # the difference between a four-minute release and a twelve-minute
        # one. The bucket refills continuously at limit-per-minute.
        per_second = budget.limit / 60.0 if budget.limit else 0.0
        wait = shortfall / per_second if per_second else budget.reset
        wait = min(max(wait, 0.0), MAX_WAIT_SECONDS)
        if wait <= 0:
            return 0.0

        self._sleep(wait)
        # Assumed refilled by that much. The next response reports the truth
        # either way, and guessing low costs one ordinary retry-after wait.
        budget.left = None
        return wait

    def _remember_budget(self, model: str, response: httpx.Response) -> None:
        """Keep what the provider said about this model's token budget."""

        budget = self._budget.setdefault(model, _Budget())

        budget.left = _whole(response.headers.get("x-ratelimit-remaining-tokens"))
        budget.limit = _whole(response.headers.get("x-ratelimit-limit-tokens")) or 0
        budget.reset = _seconds(response.headers.get("x-ratelimit-reset-tokens"))

        used = (response.json().get("usage") or {}) if _is_json(response) else {}
        if used.get("total_tokens"):
            budget.cost = int(used["total_tokens"])

    def _send(self, payload: dict) -> httpx.Response:
        """One HTTP round trip, with transport failures translated."""

        client = self._client or httpx.Client(timeout=self._timeout)
        try:
            return client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except httpx.HTTPError as error:
            raise ProviderError(f"Request to the provider failed: {error}") from error
        finally:
            if self._client is None:
                client.close()

    def _content(self, response: dict, requested_model: str) -> dict:
        """Extract and parse the message content.

        The model the provider reports is returned alongside the content, not
        the model that was asked for. A provider can serve a different build
        under the same name, and a verdict stamped with what was requested
        rather than what answered cannot be reproduced.
        """

        try:
            message = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderContentError(
                f"The provider's response had no message content: {str(response)[:300]}"
            ) from error

        try:
            parsed = json.loads(message)
        except json.JSONDecodeError as error:
            # Reachable in best-effort mode, and in strict mode only if the
            # provider ignored the constraint. Either way it is the first
            # guard's job, so it is reported rather than repaired here.
            raise ProviderContentError(
                f"The provider returned content that is not valid JSON: {message[:300]}"
            ) from error

        return {
            "content": parsed,
            "model_id": response.get("model", requested_model),
            "usage": response.get("usage", {}),
            # Carried through rather than recomputed. It belongs to the round
            # trip, not to the answer, and this is the last place that still
            # has both.
            "waited_seconds": response.get("waited_seconds", 0.0),
        }


def _retry_after(response: httpx.Response) -> float:
    """How long the provider asked us to wait, bounded.

    The header is preferred over a fixed delay because the provider knows when
    the window rolls over and this code does not. It is clamped at both ends:
    a missing or unparseable value gets a wait long enough for a per-minute
    window to have moved, and an absurd one cannot stall a run for an hour.
    """

    raw = response.headers.get("retry-after", "")
    try:
        wanted = float(raw)
    except ValueError:
        wanted = FALLBACK_WAIT_SECONDS

    return min(max(wanted, 1.0), MAX_WAIT_SECONDS)


def _is_json(response: httpx.Response) -> bool:
    """Whether the body can be read as JSON, without raising if it cannot."""

    try:
        response.json()
    except ValueError:
        return False
    return True


def _seconds(raw: str | None) -> float:
    """A provider's reset value as seconds.

    The header is written as a duration - `547ms`, `1m6.2s`, `3.5s` - rather
    than as a number, so it is parsed rather than cast. An unreadable value is
    no wait at all: pacing is an optimisation, and a wrong guess here must not
    stall a run.
    """

    if not raw:
        return 0.0

    match = re.fullmatch(
        r"(?:(?P<m>[\d.]+)m)?(?:(?P<s>[\d.]+)s)?|(?P<ms>[\d.]+)ms", raw.strip()
    )
    if match is None:
        return 0.0

    if match.group("ms"):
        return float(match.group("ms")) / 1000.0

    total = 0.0
    if match.group("m"):
        total += float(match.group("m")) * 60.0
    if match.group("s"):
        total += float(match.group("s"))
    return total


def _whole(raw: str | None) -> int | None:
    """A header as a whole number, or None when it is not one."""

    try:
        return int(raw) if raw is not None else None
    except ValueError:
        return None
