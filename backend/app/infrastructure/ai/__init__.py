"""AI access.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Provider- and model-agnostic access to a language model, as
    ARCHITECTURE.md section 5 specifies it.

    Components ask for a task and get an answer. They never name a provider or
    a model, which keeps research logic independent of vendor APIs and makes
    model choice something the research can vary rather than something the code
    decides.
"""

from .call_log import CallLog, ModelCall, summarise
from .interface import (
    AIResult,
    ConfiguredAIClient,
    StrictSchemaUnsupportedError,
    VerdictCache,
)
from .model_configuration import (
    SCHEMA_MODE_BEST_EFFORT,
    SCHEMA_MODE_JSON_OBJECT,
    SCHEMA_MODE_STRICT,
    TASK_NARRATION,
    TASK_PRIMARY_VERDICT,
    TASK_PRIMARY_VERDICT_FALLBACK,
    TASK_PRIMARY_VERDICT_LOCAL,
    TASK_VERIFICATION,
    AISettings,
    UnknownTaskError,
    ai_settings,
)
from .model_registry import (
    ModelCapabilities,
    UnknownModelError,
    capabilities_for,
    strict_schema_models,
)
from .prompt_library import PROMPT_DIRECTORY, PromptFileError, load_prompt
from .run_narration import Narration, NarrationUnavailable, RunNarrator
from .transcript_store import ModelTranscriptFileStore

__all__ = [
    "AIResult",
    "AISettings",
    "CallLog",
    "ConfiguredAIClient",
    "ModelCall",
    "ModelCapabilities",
    "ModelTranscriptFileStore",
    "Narration",
    "NarrationUnavailable",
    "PROMPT_DIRECTORY",
    "PromptFileError",
    "RunNarrator",
    "SCHEMA_MODE_BEST_EFFORT",
    "SCHEMA_MODE_JSON_OBJECT",
    "SCHEMA_MODE_STRICT",
    "StrictSchemaUnsupportedError",
    "TASK_NARRATION",
    "TASK_PRIMARY_VERDICT",
    "TASK_PRIMARY_VERDICT_FALLBACK",
    "TASK_PRIMARY_VERDICT_LOCAL",
    "TASK_VERIFICATION",
    "UnknownModelError",
    "UnknownTaskError",
    "VerdictCache",
    "ai_settings",
    "capabilities_for",
    "load_prompt",
    "summarise",
    "strict_schema_models",
]
