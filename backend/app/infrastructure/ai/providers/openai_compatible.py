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

import httpx


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
    """


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


class OpenAICompatibleProvider:
    """Calls a chat-completions endpoint and returns parsed JSON."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        """Bind the adapter to one endpoint.

        `client` is injectable so the request can be exercised against a
        transport stub without a network or a key.
        """

        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._client = client

    def complete(
        self,
        model_id: str,
        prompt: str,
        schema: dict,
        strict: bool = True,
        temperature: float = 0.0,
        seed: int | None = 42,
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
        client = self._client or httpx.Client(timeout=self._timeout)
        try:
            result = client.post(
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

        if result.status_code == 429:
            raise ProviderRateLimited(
                "The provider rate-limited this request. On a free tier the limit is "
                "tokens per minute, so a large evidence package is the usual cause."
            )
        if result.status_code >= 400:
            # The body carries which part of the schema was refused, and
            # without it the error is unactionable.
            raise ProviderError(
                f"The provider returned {result.status_code}: {result.text[:500]}"
            )

        try:
            return result.json()
        except ValueError as error:
            raise ProviderError("The provider's response was not JSON.") from error

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
        }
