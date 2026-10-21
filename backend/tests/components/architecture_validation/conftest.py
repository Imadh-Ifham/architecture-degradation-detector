"""Keep the developer's `.env` out of this component's tests.

Author: Aman Mohamed M.A
Date: 2026-10-21
Description:
    `AISettings` reads `.env`, which is correct for the application and wrong
    for a test suite: it makes the result depend on a file that is not in the
    repository, so the same commit passes on one machine and fails on another.

    **This has now happened twice, and the second time it turned fifteen tests
    red.** First when `AI_CACHE_ENABLED` was flipped to prove the models were
    being called, and again when the provider was switched to DeepSeek - every
    test asserting a default model name or a strict schema went with it. Both
    times the code was correct and the suite was reading a configuration file.

    So the file is neutralised for the whole session, and every test gets the
    defaults in `model_configuration.py` plus whatever it passes explicitly.
    A test that wants a value now has to say so, which is the only arrangement
    where the assertion means anything.

    **The live tests are exempt**, because `.env` is the whole point of them:
    they call the configured provider with the configured key, and a live test
    against the defaults would be testing a deployment nobody has.

    The same guard sits in `tests/infrastructure/ai/conftest.py`. Duplicated
    rather than shared, because a conftest only applies to its own directory
    and the alternative is editing the suite-wide one, which belongs to
    another component.
"""

import pytest

from app.infrastructure.ai.model_configuration import AISettings


@pytest.fixture(autouse=True)
def ignore_the_developers_env(request):
    """Build `AISettings` from the defaults, not from `.env`.

    Scoped per test rather than per session so the `live` marker can opt out
    one test at a time, and restored afterwards so nothing leaks into a suite
    run in the same process.
    """

    if request.node.get_closest_marker("live"):
        yield
        return

    original = AISettings.model_config.get("env_file")
    AISettings.model_config["env_file"] = None
    try:
        yield
    finally:
        AISettings.model_config["env_file"] = original
