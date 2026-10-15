"""AI provider adapters.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Concrete adapters, one per API contract rather than one per vendor.

    `openai_compatible` covers every hosted and local runtime that exposes the
    OpenAI chat-completions API, which is all of the ones under consideration.
    Naming it for the contract rather than for one vendor is what keeps a
    provider change to three environment values.
"""

from .fake import FakeProvider
from .openai_compatible import OpenAICompatibleProvider, ProviderError

__all__ = ["FakeProvider", "OpenAICompatibleProvider", "ProviderError"]
