"""A finished run, read back as prose.

Author: Aman Mohamed M.A
Date: 2026-10-21
Description:
    Asks a model to write the plain-English account of a run that has already
    been decided.

    This is a reading of the result and not a part of it, and the distinction
    is the only thing about this module that is delicate. The pipeline has
    eight stages, two of which call a model; this is none of them. Nothing it
    produces is stored on a fact, published in the graph, or read by the next
    component. If the narration is wrong, a verdict is still right, and the
    figures beside it on the screen are the ones to believe.

    That is also why it takes a brief rather than the run: a dict of numbers
    already published cannot be used to re-derive a verdict, and a narrator
    handed the evidence packages could quietly become a third judge nobody
    counted. The brief is built by the layer that already holds the published
    document, and this module cannot reach anything it was not given.

    It lives under infrastructure because that is all it is - one prompt and
    one call through the same interface everything else uses, with the model
    named by a task so this file does not know which one answers either.
"""

import hashlib
import json
from dataclasses import dataclass

from app.domain.model_access import ModelAccessError

from .model_configuration import TASK_NARRATION

MAX_SAMPLED_CALLS = 6
MAX_PROMPT_CHARACTERS = 1_400
MAX_RESPONSE_CHARACTERS = 700


@dataclass(frozen=True)
class Narration:
    """The account, with what wrote it attached.

    `model_id` is on the result rather than assumed by the reader, because the
    whole point of showing this beside the verdicts is that a reader can tell
    which sentences a model produced.
    """

    headline: str
    what_it_read: str
    what_it_concluded: str
    what_to_distrust: str
    model_id: str
    prompt_version: str
    cached: bool

    def to_dict(self) -> dict:
        return {
            "headline": self.headline,
            "what_it_read": self.what_it_read,
            "what_it_concluded": self.what_it_concluded,
            "what_to_distrust": self.what_to_distrust,
            "model_id": self.model_id,
            "prompt_version": self.prompt_version,
            "cached": self.cached,
        }


class NarrationUnavailable(RuntimeError):
    """No model could write the account.

    Raised rather than returning a sentence assembled from the figures. A
    template would read like the model's account at a glance, and the one
    thing this feature must never do is make it harder to tell which parts of
    a screen a model wrote.
    """


class RunNarrator:
    """Turns a brief of published figures into readable prose."""

    def __init__(self, ai, prompt) -> None:
        """Takes the model port and the loaded prompt, as the two judges do."""

        self._ai = ai
        self._prompt = prompt

    def narrate(self, brief: dict, calls: list[dict]) -> Narration:
        """Write the account of one run.

        `calls` is a sample of the run's transcript rather than all of it: the
        account is about the run, and a hundred near-identical requests say
        nothing a handful does not. Each one is shortened, because the prompt
        text of a single fact can be longer than everything else here put
        together.
        """

        rendered = _render(self._prompt, brief, calls)

        try:
            result = self._ai.complete(
                task=TASK_NARRATION,
                prompt=rendered,
                schema=narration_schema(),
                prompt_version=self._prompt.version,
                evidence_hash=_brief_hash(brief),
            )
        except ModelAccessError as error:
            raise NarrationUnavailable(
                f"No model could write the account of this run: {error}"
            ) from error

        return Narration(
            headline=result.content["headline"],
            what_it_read=result.content["what_it_read"],
            what_it_concluded=result.content["what_it_concluded"],
            what_to_distrust=result.content["what_to_distrust"],
            model_id=result.model_id,
            prompt_version=result.prompt_version,
            cached=result.cached,
        )


def narration_schema() -> dict:
    """The shape the account has to come back in.

    Four fields rather than one block of text, so the screen can place each
    paragraph under a heading it did not have to guess at - and so the
    paragraph a reader most needs cannot be the one the model left out.
    """

    return {
        "type": "object",
        "properties": {
            "what_it_read": {
                "type": "string",
                "description": "The input, and what the models were shown.",
            },
            "what_it_concluded": {
                "type": "string",
                "description": "The verdicts, and who produced them.",
            },
            "what_to_distrust": {
                "type": "string",
                "description": "The weakest part of this result, and why.",
            },
            "headline": {
                "type": "string",
                "description": "One sentence under twenty words.",
            },
        },
    }


def _render(template, brief: dict, calls: list[dict]) -> str:
    """Build the request text from the brief and a sample of the calls."""

    body = template.body
    for name, value in (
        ("run_id", str(brief.get("run_id", "unknown"))),
        ("release", str(brief.get("release_id", "unknown"))),
        ("repository", str(brief.get("repository_id", "unknown"))),
        ("figures", _render_figures(brief)),
        ("calls", _render_calls(calls)),
    ):
        body = body.replace("{{" + name + "}}", value)

    return f"{template.system}\n\n{body}"


def _render_figures(brief: dict) -> str:
    """The brief as lines of name and value, nested one level.

    Printed rather than dumped as JSON because the model is being asked for
    prose and the figures read as facts this way. Nothing is renamed on the
    way: a number the account quotes has to be findable on the screen beside
    it, under the same name.
    """

    lines = []
    for name, value in brief.items():
        if isinstance(value, dict):
            lines.append(f"{name}:")
            lines.extend(f"  {key}: {entry}" for key, entry in value.items())
        else:
            lines.append(f"{name}: {value}")
    return "\n".join(lines)


def _render_calls(calls: list[dict]) -> str:
    """A shortened sample of the transcript, as request and answer pairs."""

    if not calls:
        return "No model call was recorded for this run."

    rendered = []
    for call in calls[:MAX_SAMPLED_CALLS]:
        answer = call.get("response")
        settled = json.dumps(answer) if answer else str(call.get("error"))
        rendered.append(
            f"[{call.get('sequence')}] task {call.get('task')}, model "
            f"{call.get('answered_model')}, {call.get('outcome')}\n"
            f"sent:\n{_shorten(str(call.get('prompt', '')), MAX_PROMPT_CHARACTERS)}\n"
            f"answered:\n{_shorten(settled, MAX_RESPONSE_CHARACTERS)}"
        )
    return "\n\n".join(rendered)


def _shorten(text: str, limit: int) -> str:
    """Cut `text` to `limit`, saying so rather than cutting silently."""

    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n[... {len(text) - limit} more characters]"


def _brief_hash(brief: dict) -> str:
    """The cache key's evidence component, so a re-read of one run is free.

    The brief is the whole input, so hashing it means the account is paid for
    once per distinct set of figures - and a re-run that changed a count
    writes a new account rather than serving the old one.
    """

    material = json.dumps(brief, sort_keys=True, default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


__all__ = ["Narration", "NarrationUnavailable", "RunNarrator", "narration_schema"]
