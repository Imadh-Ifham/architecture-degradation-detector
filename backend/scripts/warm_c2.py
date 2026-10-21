"""Warm the verdict cache before a demonstration, and prove it is warm.

Run from ``backend/``::

    uv run python -m scripts.warm_c2 --repository microservices-demo-ffb04a16f525 \
        --release v0.8.1 --release v0.9.0 --release v0.10.0

Why this exists. A release validated for the first time costs about four
minutes, because the free tier allows eight thousand tokens a minute and one
release spends roughly thirty-three thousand across its calls. A release
validated a second time costs seconds, because every answer replays from a
cache keyed on the evidence - and a replayed answer is still the model's own.

So the four minutes is paid once, the night before, by this script. What it
adds over clicking the button three times is the part that was getting it
wrong: releases share one per-minute token budget, so running them
back-to-back drains it and the later ones queue or give up. This waits
between them.

It then runs every release a second time and reports whether each one is
genuinely warm. ``live: 0`` is the only evidence that matters, and reading it
off the transcript is the difference between believing the cache is warm and
knowing it.
"""

import time
from dataclasses import dataclass

import httpx
import typer

app = typer.Typer(add_completion=False, help=__doc__)

DEFAULT_BASE_URL = "http://127.0.0.1:8000"

PAUSE_SECONDS = 70.0
"""How long to wait between releases while warming.

The budget is per minute, so a little over a minute lets it refill completely.
Shorter is how the first attempt produced a call that waited sixty seconds and
then gave up, costing that fact its verification.
"""


@dataclass
class Outcome:
    """One release's run, as the numbers a reader checks."""

    release: str
    seconds: float
    calls: int
    live: int
    replayed: int
    unavailable: int
    confidence: float
    status: str

    @property
    def is_warm(self) -> bool:
        """Whether a re-run of this release would cost nothing.

        `live == 0` and nothing unanswered. A run with one live call left is
        a run that can still queue behind a rate limit, which is the whole
        failure this script exists to prevent on the day.
        """

        return self.live == 0 and self.unavailable == 0


def _validate(client: httpx.Client, repository: str, release: str, verify: bool) -> Outcome:
    """Run one release and read its transcript back."""

    started = time.perf_counter()
    run = client.post(
        "/validations",
        json={
            "repository_id": repository,
            "release_id": release,
            "decision_mode": "combined",
            "verify": verify,
        },
        timeout=900.0,
    )
    seconds = time.perf_counter() - started

    if run.status_code != 200:
        raise typer.BadParameter(
            f"{release}: the run was refused ({run.status_code}) - {run.text[:300]}"
        )

    body = run.json()
    transcript = client.get(
        "/validations/transcript",
        params={"repository_id": repository, "release_id": release},
        timeout=60.0,
    )
    summary = transcript.json()["summary"] if transcript.status_code == 200 else {}

    return Outcome(
        release=release,
        seconds=seconds,
        calls=summary.get("calls", 0),
        live=summary.get("live", 0),
        replayed=summary.get("replayed", 0),
        unavailable=summary.get("unavailable", 0),
        confidence=body.get("validation_confidence", 0.0),
        status=body.get("status", "unknown"),
    )


def _report(title: str, outcomes: list[Outcome]) -> None:
    typer.echo("")
    typer.echo(title)
    typer.echo(f"  {'release':12} {'seconds':>8} {'calls':>6} {'live':>5} {'replay':>7} "
               f"{'unans':>6} {'conf':>6}  state")
    for row in outcomes:
        typer.echo(
            f"  {row.release:12} {row.seconds:8.1f} {row.calls:6} {row.live:5} "
            f"{row.replayed:7} {row.unavailable:6} {row.confidence:6.2f}  "
            f"{'WARM' if row.is_warm else 'still cold'}"
        )


@app.command()
def main(
    repository: str = typer.Option(..., help="The repository id, as ingestion stored it."),
    release: list[str] = typer.Option(..., help="A release to warm. Repeat for each."),
    base_url: str = typer.Option(DEFAULT_BASE_URL, help="Where the backend is listening."),
    verify: bool = typer.Option(True, help="Ask the second model too. Off halves the tokens."),
    pause: float = typer.Option(PAUSE_SECONDS, help="Seconds between releases while warming."),
    check_only: bool = typer.Option(
        False, help="Skip warming and only report whether each release is already warm."
    ),
) -> None:
    """Warm every named release, then prove each one replays."""

    client = httpx.Client(base_url=base_url.rstrip("/"))

    try:
        client.get("/validations/pipeline", timeout=10.0).raise_for_status()
    except httpx.HTTPError as error:
        raise typer.BadParameter(
            f"No backend at {base_url} - start it first. ({error})"
        ) from error

    if not check_only:
        warmed: list[Outcome] = []
        for index, name in enumerate(release):
            typer.echo(f"warming {name} ({index + 1} of {len(release)})...")
            warmed.append(_validate(client, repository, name, verify))
            if index < len(release) - 1:
                # The token budget is per minute and shared across runs, not
                # per run. Without this the later releases queue behind the
                # earlier ones and a call can give up entirely.
                typer.echo(f"  waiting {pause:.0f}s for the token budget to refill")
                time.sleep(pause)
        _report("first pass - paying for the answers", warmed)

    typer.echo("")
    typer.echo("second pass - this is what the demonstration will do")
    confirmed = [_validate(client, repository, name, verify) for name in release]
    _report("second pass - replaying", confirmed)

    cold = [row for row in confirmed if not row.is_warm]
    total = sum(row.seconds for row in confirmed)

    typer.echo("")
    typer.echo(f"  all {len(release)} releases replayed in {total:.1f}s")

    if cold:
        typer.echo("")
        typer.echo("  NOT READY. These still make live calls, so they can queue:")
        for row in cold:
            typer.echo(f"    {row.release}: {row.live} live, {row.unavailable} unanswered")
        typer.echo("  Run this again - a release that gave up on a rate limit warms next time.")
        raise typer.Exit(code=1)

    typer.echo("  every release is warm. A re-run costs no model call.")


if __name__ == "__main__":
    app()
