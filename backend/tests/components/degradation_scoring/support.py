# Shared test helpers for C4: default config, fixture loading and in-memory port fakes.

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.components.degradation_scoring.config import C4Config
from app.core.config import Settings

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "degradation_scoring"


def default_config(**overrides: Any) -> C4Config:
    # C4Config from the declared defaults only, so a developer's .env cannot change a test.
    settings = Settings.model_construct(
        postgres_host="localhost",
        postgres_db="db",
        postgres_user="user",
        postgres_password="password",
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="password",
    )
    return C4Config.from_settings(settings).model_copy(update=overrides)


def load_fixture(relative: str) -> Any:
    return json.loads((FIXTURES / relative).read_text(encoding="utf-8"))


class FakeEventSource:
    # DegradationEventSource over in-memory payloads; records what was asked for.

    def __init__(self, payloads: Sequence[object]) -> None:
        self._payloads = list(payloads)
        self.requests: list[tuple[str, str]] = []

    def fetch(self, system_id: str, release_id: str) -> Sequence[object]:
        self.requests.append((system_id, release_id))
        return list(self._payloads)


class FakeGraphSource:
    # ArchitectureGraphSource over in-memory documents keyed by release; records requests.

    def __init__(self, documents: dict[str, object]) -> None:
        self._documents = documents
        self.requests: list[tuple[str, str]] = []

    def fetch(self, system_id: str, release_id: str) -> object:
        self.requests.append((system_id, release_id))
        return self._documents[release_id]
