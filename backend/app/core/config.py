"""Application settings.

Author: Imadh Ifham
Date: 2026-10-14
Description:
    Loads configuration from three sources, in increasing order of precedence:

      1. the field defaults declared here,
      2. `backend/config.ini`, which is committed and holds non-sensitive
         tuning values shared by every developer and environment,
      3. environment variables and `backend/.env`, which hold secrets and
         environment-specific values and are never committed.

    The split exists so that a committed file documents the tuning knobs, while
    credentials and machine-specific paths stay out of version control. Because
    the environment wins, anything in `config.ini` can still be overridden per
    machine or per deployment.
"""

import configparser
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Literal

from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

#: Committed, non-sensitive configuration. Resolved relative to this file so
#: the configured values are found regardless of the process working directory.
CONFIG_INI_PATH = Path(__file__).resolve().parents[2] / "config.ini"

#: Sections of `config.ini` that map onto settings. A section name is a
#: namespace in the file only; the field names stay flat.
CONFIG_INI_SECTIONS = (
    "app",
    "git",
    "inventory",
    "manifest_analysis",
    "validation",
    "scoring",
)


class ConfigIniSettingsSource(PydanticBaseSettingsSource):
    """Reads settings from a committed INI file.

    `pydantic-settings` supports dotenv and secrets files natively but not INI,
    so the file is read through `configparser` and flattened into the mapping
    the settings class expects. Unknown keys are ignored rather than rejected,
    because the file is shared and may be ahead of a given deployment.
    """

    def __init__(self, settings_cls: type[BaseSettings], path: Path = CONFIG_INI_PATH) -> None:
        """Store the settings class and the INI path to read."""

        super().__init__(settings_cls)
        self._path = Path(path)

    def __call__(self) -> dict[str, Any]:
        """Return the INI values as a flat mapping, or nothing if absent."""

        if not self._path.is_file():
            return {}

        parser = configparser.ConfigParser()

        try:
            parser.read(self._path, encoding="utf-8")
        except configparser.Error:
            # A malformed INI file must not stop the application from starting;
            # the defaults and the environment still apply.
            return {}

        values: dict[str, Any] = {}

        for section in CONFIG_INI_SECTIONS:
            if not parser.has_section(section):
                continue

            for key, value in parser.items(section):
                values[key] = value

        return values

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        """Unused: `__call__` returns the whole mapping instead."""

        return None, field_name, False


BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration for the backend."""

    app_name: str = "Architecture Degradation Detector"
    app_env: str = "development"
    # Published on the generated API documentation, so a client can tell two
    # deployments apart.
    app_version: str = "0.1.0"

    postgres_host: str
    postgres_port: int = 5434
    postgres_db: str
    postgres_user: str
    postgres_password: str

    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str

    # Local workspace holding ingested (cloned) repositories.
    repositories_root: Path = Path(gettempdir()) / "add-repositories"

    # Where the architecture validation component reads its input from.
    # `graph` is recovery's own store and works for any repository that has
    # been ingested; `snapshot` and `inventory` read a recording and only
    # answer for releases somebody recorded. Never a silent fallback between
    # them: whichever answered is stamped on the run's provenance, so a result
    # always says which input produced it.
    architecture_source: str = "graph"
    # Derived rather than configured, because it is the same relative location
    # on every machine and an absolute path does not belong in a committed file.
    snapshot_root: Path = BACKEND_ROOT / "data" / "snapshots"
    # The decision history the validation component accumulates per
    # repository. Output rather than input, so it lives under the ignored
    # artifacts directory; the demonstration's corpus is a committed fixture.
    decision_log_root: Path = BACKEND_ROOT / "artifacts" / "validation" / "decisions"
    # Where a completed validation run publishes the one artifact the next
    # component reads. One file per run, kept, plus a `latest` pointer moved by
    # atomic rename - under the ignored artifacts directory, because it is
    # output and because the committed copy is a single golden fixture.
    validated_graph_root: Path = BACKEND_ROOT / "artifacts" / "validated"
    # What a validation run sent to each model and what came back, kept beside
    # the graph that run published rather than inside it. Separate because the
    # graph is the contract the next component reads and this is evidence a
    # person reads - and because a transcript nobody deletes would otherwise
    # grow the one artifact that has to stay small enough to diff.
    model_transcript_root: Path = (
        BACKEND_ROOT / "artifacts" / "validation" / "transcripts"
    )
    clone_timeout_seconds: int = 300

    # Repository inventory limits.
    max_files: int = 20_000
    max_file_size_bytes: int = 5_000_000
    max_depth: int = 32
    max_manifest_bytes: int = 262_144
    grouping_depth: int = 2
    extra_excluded_directories: str = ""

    # Manifest analysis limits.
    manifest_max_bytes: int = 1_048_576
    manifest_max_documents: int = 64

    # Degradation detection (C3), when run from the API. The demo file is the
    # research defaults with `trend.min_releases` lowered to 3, so a stack of a
    # few validated releases gets trend results; the CLI keeps reading
    # configs/default.yaml. Every run stores the hash of the config it used.
    degradation_config_path: Path = BACKEND_ROOT / "configs" / "demo.yaml"
    # Where an API run writes what the scoring phase reads: events.json and the
    # release package of the window's last release, per run and as `latest`.
    degradation_outputs_root: Path = BACKEND_ROOT / "artifacts" / "degradation"

    # Degradation scoring (C4); see the [scoring] section of config.ini. The
    # defaults are the values fixed in
    # app/components/degradation_scoring/CLAUDE.md §4-§5. Names keep the
    # `scoring_` prefix because config.ini flattens every section into one
    # namespace and names like `seed` or `method` would collide.
    # Run outputs (report, manifest, quarantine). Output rather than input, so
    # it lives under the ignored artifacts directory.
    scoring_outputs_root: Path = BACKEND_ROOT / "artifacts" / "scoring"
    scoring_seed: int = 42
    scoring_rank_only_confirmed: bool = False
    scoring_graph_reverse_edges: bool = False
    scoring_resolution_prefix_confidence: float = 0.7
    scoring_br_weight_fan_in_ratio: float = 0.25
    scoring_br_weight_pagerank: float = 0.25
    scoring_br_weight_betweenness: float = 0.25
    scoring_br_weight_depth: float = 0.25
    scoring_pagerank_alpha: float = 0.85
    scoring_betweenness_exact_max_nodes: int = 5000
    scoring_betweenness_sample_k: int = 500
    scoring_hotspot_half_life_releases: float = 2.0
    scoring_cochange_threshold: int = 5
    scoring_max_files_per_commit: int = 50
    scoring_eh_weight_churn_decayed: float = 0.25
    scoring_eh_weight_authors: float = 0.25
    scoring_eh_weight_coupling: float = 0.25
    scoring_eh_weight_bugfix_ratio: float = 0.25
    scoring_history_include_globs: str = (
        "*.py,*.java,*.go,*.js,*.ts,*.cs,*.kt,*.rb,*.php,*.cpp,*.c,*.h"
    )
    scoring_history_exclude_globs: str = (
        "**/vendor/**,**/node_modules/**,**/generated/**,**/*_pb2.py,**/*.pb.go,"
        "**/test*/fixtures/**,*.min.js,"
        "**/target/**,**/build/**,**/dist/**,**/bin/**,**/obj/**"
    )
    scoring_ps_weight_consecutive_releases: float = 0.7
    scoring_ps_weight_growth_slope: float = 0.3
    scoring_adr_semantic_fallback_enabled: bool = False
    scoring_adr_semantic_similarity_threshold: float = 0.6
    scoring_winsor_lower_percentile: float = 5.0
    scoring_winsor_upper_percentile: float = 95.0
    scoring_small_n_threshold: int = 10
    scoring_ahp_max_consistency_ratio: float = 0.10
    scoring_weights_version: str = "ahp_v1"
    scoring_method: Literal["topsis", "lambdamart"] = "topsis"
    scoring_topsis_mode: Literal["fixed_reference", "classic"] = "fixed_reference"
    scoring_explain_top_n: int = 10
    scoring_retriever_top_k: int = 8
    scoring_explanation_max_words: int = 120
    scoring_llm_temperature: float = 0.0
    scoring_nli_entailment_threshold: float = 0.5
    scoring_nli_contradiction_threshold: float = 0.5
    scoring_ground_truth_horizon_releases: int = 2
    scoring_ground_truth_min_ops: int = 2
    scoring_bootstrap_resamples: int = 1000
    scoring_bootstrap_confidence: float = 0.95
    scoring_random_baseline_permutations: int = 100

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # So a key renamed in the environment fails loudly rather than being
        # silently ignored.
        extra="forbid",
        # Read only this class's own fields from the file. `.env` is shared
        # with `AISettings`, which owns the `ai_*` names, so without this
        # `extra="forbid"` rejects the whole file over a key that belongs to
        # another settings class and every consumer of these settings fails.
        # The environment source already ignores names it does not own; this
        # makes the file source consistent with it.
        dotenv_filtering="only_existing",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Order the sources: explicit arguments, environment, dotenv, config.ini.

        `config.ini` is last, so a value set in the environment or in `.env`
        always wins over the committed default.
        """

        return (
            init_settings,
            env_settings,
            dotenv_settings,
            ConfigIniSettingsSource(settings_cls),
            file_secret_settings,
        )


settings = Settings()
