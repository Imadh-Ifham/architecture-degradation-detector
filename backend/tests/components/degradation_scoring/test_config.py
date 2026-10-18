# Tests for the degradation scoring configuration.
import configparser

import pytest
from pydantic import TypeAdapter, ValidationError

from app.components.degradation_scoring.config import SETTINGS_PREFIX, C4Config
from app.core.config import BACKEND_ROOT, CONFIG_INI_PATH, CONFIG_INI_SECTIONS, Settings

# Value -> section it comes from.
EXPECTED_DEFAULTS = {
    "scoring_outputs_root": BACKEND_ROOT / "artifacts" / "scoring",  # §6
    "scoring_seed": 42,  # §7 determinism
    "scoring_rank_only_confirmed": False,  # §4.1, C4-ADR-007 (C3 emits PENDING until M7)
    "scoring_graph_reverse_edges": False,  # §4.3 "A -> B" = A depends on B
    "scoring_resolution_prefix_confidence": 0.7,  # §5.1
    "scoring_br_weight_fan_in_ratio": 0.25,  # §5.1 equal weights
    "scoring_br_weight_pagerank": 0.25,  # §5.1
    "scoring_br_weight_betweenness": 0.25,  # §5.1
    "scoring_br_weight_depth": 0.25,  # §5.1
    "scoring_pagerank_alpha": 0.85,  # §5.1
    "scoring_betweenness_exact_max_nodes": 5000,  # §5.1
    "scoring_betweenness_sample_k": 500,  # §5.1
    "scoring_hotspot_half_life_releases": 2.0,  # §5.2
    "scoring_cochange_threshold": 5,  # §5.2 theta
    "scoring_max_files_per_commit": 50,  # §5.2
    "scoring_ps_weight_consecutive_releases": 0.7,  # §5.4
    "scoring_ps_weight_growth_slope": 0.3,  # §5.4
    "scoring_adr_semantic_fallback_enabled": False,  # §5.3 post-PP1
    "scoring_adr_semantic_similarity_threshold": 0.6,  # §5.3 tau
    "scoring_winsor_lower_percentile": 5.0,  # §5.5
    "scoring_winsor_upper_percentile": 95.0,  # §5.5
    "scoring_small_n_threshold": 10,  # §5.5
    "scoring_ahp_max_consistency_ratio": 0.10,  # §5.6
    "scoring_weights_version": "ahp_v1",  # §5.6
    "scoring_method": "topsis",  # §5.8
    "scoring_topsis_mode": "fixed_reference",  # §5.7
    "scoring_explain_top_n": 10,  # §5.9
    "scoring_retriever_top_k": 8,  # §5.9
    "scoring_explanation_max_words": 120,  # §5.9
    "scoring_llm_temperature": 0.0,  # §5.9
    "scoring_nli_entailment_threshold": 0.5,  # §5.9
    "scoring_nli_contradiction_threshold": 0.5,  # §5.9
    "scoring_ground_truth_horizon_releases": 2,  # §5.10 k
    "scoring_ground_truth_min_ops": 2,  # §5.10
    "scoring_bootstrap_resamples": 1000,  # §5.10
    "scoring_bootstrap_confidence": 0.95,  # §5.10
    "scoring_random_baseline_permutations": 100,  # §5.10
}

# A path is machine-specific, so it is set in .env rather than the committed file.
NOT_IN_CONFIG_INI = {"scoring_outputs_root"}


def _scoring_field_names() -> set[str]:
    return {name for name in Settings.model_fields if name.startswith(SETTINGS_PREFIX)}


def _settings_with_defaults() -> Settings:
    # Only the settings without a default are given; every scoring_* field
    # keeps its declared default.
    return Settings.model_construct(
        postgres_host="localhost",
        postgres_db="db",
        postgres_user="user",
        postgres_password="password",
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="password",
    )


def _config_ini_scoring_section() -> dict[str, str]:
    parser = configparser.ConfigParser()
    parser.read(CONFIG_INI_PATH, encoding="utf-8")
    return dict(parser.items("scoring"))


def test_every_scoring_setting_has_a_pinned_default() -> None:
    assert _scoring_field_names() == set(EXPECTED_DEFAULTS)


@pytest.mark.parametrize("name", sorted(EXPECTED_DEFAULTS))
def test_scoring_default_matches_claude_md(name: str) -> None:
    assert Settings.model_fields[name].default == EXPECTED_DEFAULTS[name]


def test_scoring_section_is_read_from_config_ini() -> None:
    assert "scoring" in CONFIG_INI_SECTIONS


def test_config_ini_lists_every_scoring_setting_except_paths() -> None:
    assert set(_config_ini_scoring_section()) == set(EXPECTED_DEFAULTS) - NOT_IN_CONFIG_INI


@pytest.mark.parametrize("name", sorted(set(EXPECTED_DEFAULTS) - NOT_IN_CONFIG_INI))
def test_config_ini_value_matches_claude_md(name: str) -> None:
    raw = _config_ini_scoring_section()[name]
    adapter: TypeAdapter[object] = TypeAdapter(Settings.model_fields[name].annotation)
    parsed = adapter.validate_python(raw)

    assert parsed == EXPECTED_DEFAULTS[name]


def test_c4_config_mirrors_the_scoring_settings() -> None:
    expected_fields = {name.removeprefix(SETTINGS_PREFIX) for name in EXPECTED_DEFAULTS}

    assert set(C4Config.model_fields) == expected_fields


def test_from_settings_copies_every_value_without_the_prefix() -> None:
    config = C4Config.from_settings(_settings_with_defaults())

    for name, value in EXPECTED_DEFAULTS.items():
        assert getattr(config, name.removeprefix(SETTINGS_PREFIX)) == value


def test_c4_config_is_read_only() -> None:
    config = C4Config.from_settings(_settings_with_defaults())

    with pytest.raises(ValidationError):
        config.seed = 7
