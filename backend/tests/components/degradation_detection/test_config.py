"""C3 configuration: YAML -> C3Config, and the config hash stored on every run (plan Section 5)."""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.components.degradation_detection.config import (
    DEFAULT_CATALOG_PATH,
    DEFAULT_CONFIG_PATH,
    C3Config,
    CatalogConfig,
    ConfigError,
    load_config,
)
from app.domain.audit_entry import Verdict
from app.domain.degradation_event import TimeAxis, Worsening


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


# --- defaults ------------------------------------------------------------------------------


def test_default_file_holds_the_plan_defaults() -> None:
    cfg = load_config()

    assert (cfg.gate.accept, cfg.gate.exclude) == (0.70, 0.50)
    assert cfg.detection.hub.iqr_k == 1.5
    assert cfg.detection.unstable.ratio == 0.3
    assert cfg.detection.oversized.z_max == 3.5
    assert cfg.detection.big_ball_of_mud.largest_scc_share_min == 0.25
    assert cfg.detection.big_ball_of_mud.modularity_max == 0.30
    assert cfg.align.rename_min == 0.75
    assert cfg.align.ambiguity_margin == 0.05
    assert cfg.tracking.instance_jaccard_min == 0.5
    assert cfg.trend.alpha == 0.05
    assert cfg.trend.gate_on == "q"
    assert cfg.trend.min_releases == 8
    assert cfg.trend.exact_below == 10
    assert cfg.trend.n_perm == 20000
    assert cfg.trend.seed == 20261013
    assert cfg.trend.time_axis is TimeAxis.ORDINAL
    assert cfg.metrics.c1_passthrough[0].name == "c1.lcom"
    assert cfg.metrics.c1_passthrough[0].worsening is Worsening.INCREASE
    assert cfg.review.note_required_for == (Verdict.REJECTED, Verdict.NEEDS_INVESTIGATION)


def test_default_file_and_built_in_defaults_are_the_same() -> None:
    """The defaults live in two places (model and YAML); this keeps them from drifting."""
    assert load_config(DEFAULT_CONFIG_PATH) == C3Config()


def test_context_is_disabled_by_default() -> None:
    """PP1 runs the trend-only baseline (D-28)."""
    assert load_config().context.enabled is False


def test_empty_file_gives_the_defaults(tmp_path: Path) -> None:
    assert load_config(write(tmp_path, "")) == C3Config()


def test_file_overrides_only_what_it_names(tmp_path: Path) -> None:
    cfg = load_config(write(tmp_path, "trend:\n  alpha: 0.01\n"))

    assert cfg.trend.alpha == 0.01
    assert cfg.trend.min_releases == 8


# --- extra="forbid": a typo fails at start-up ------------------------------------------------


def test_typo_in_a_top_level_key_fails(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="trnd"):
        load_config(write(tmp_path, "trnd:\n  alpha: 0.01\n"))


def test_typo_in_a_nested_key_fails(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="alhpa"):
        load_config(write(tmp_path, "trend:\n  alhpa: 0.01\n"))


def test_config_is_immutable() -> None:
    cfg = C3Config()

    with pytest.raises(ValidationError):
        cfg.trend.alpha = 0.5  # type: ignore[misc]


# --- value checks ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "trend:\n  alpha: 0\n",
        "trend:\n  alpha: 1.5\n",
        "trend:\n  gate_on: z\n",
        "trend:\n  min_releases: 1\n",
        "gate:\n  accept: 0.4\n  exclude: 0.5\n",
        "align:\n  weights: {name: 0.5, neighbours: 0.4, size: 0.2}\n",
        "ingest:\n  release_line_regex: '('\n",
        "metrics:\n  c1_passthrough: [{name: lcom, unit: lcom, worsening: INCREASE}]\n",
        "metrics:\n  c1_passthrough: [{name: c1.lcom, unit: lcom, worsening: UP}]\n",
        "detection:\n  modularity: {algorithm: louvain}\n",
    ],
    ids=[
        "alpha-zero",
        "alpha-above-one",
        "unknown-gate",
        "too-few-releases",
        "gate-accept-below-exclude",
        "weights-do-not-sum-to-one",
        "bad-regex",
        "passthrough-without-c1-prefix",
        "unknown-worsening",
        "randomised-modularity",
    ],
)
def test_invalid_values_fail(tmp_path: Path, text: str) -> None:
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, text))


def test_missing_file_fails(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="nope.yaml"):
        load_config(tmp_path / "nope.yaml")


def test_malformed_yaml_fails(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "trend: [unclosed\n"))


def test_non_mapping_yaml_fails(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="mapping"):
        load_config(write(tmp_path, "- a\n- b\n"))


# --- config_hash -----------------------------------------------------------------------------


def test_hash_has_the_contract_format() -> None:
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", C3Config().config_hash)


def test_hash_is_stable_across_loads() -> None:
    assert load_config().config_hash == load_config().config_hash


def test_hash_ignores_key_order_comments_and_omitted_defaults(tmp_path: Path) -> None:
    a = load_config(write(tmp_path, "trend:\n  alpha: 0.01\ngate:\n  accept: 0.8\n"))
    b = load_config(
        write(
            tmp_path,
            "# same run, written differently\n"
            "gate: {accept: 0.80, exclude: 0.5}\n"
            "trend: {min_releases: 8, alpha: 0.01}\n",
        )
    )

    assert a.config_hash == b.config_hash


def test_hash_changes_when_alpha_changes(tmp_path: Path) -> None:
    changed = load_config(write(tmp_path, "trend:\n  alpha: 0.01\n"))

    assert changed.config_hash != C3Config().config_hash


def test_hash_changes_when_a_detector_threshold_changes(tmp_path: Path) -> None:
    changed = load_config(write(tmp_path, "detection:\n  oversized: {z_max: 3.0}\n"))

    assert changed.config_hash != C3Config().config_hash


# --- detector catalog (configs/catalog.yaml) -------------------------------------------------

UNIVERSAL = (
    "CyclicDependency",
    "HubLikeElement",
    "UnstableDependency",
    "OversizedElement",
    "BigBallOfMud",
)


def write_catalog(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "catalog.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_default_catalog_runs_universal_everywhere_and_shared_persistence_on_microservices() -> (
    None
):
    catalog = load_config().catalog

    assert catalog.enabled == {"*": UNIVERSAL, "microservices": ("SharedPersistence",)}


def test_default_catalog_file_and_built_in_defaults_are_the_same() -> None:
    assert load_config(catalog_path=DEFAULT_CATALOG_PATH).catalog == CatalogConfig()


def test_catalog_is_read_from_the_catalog_file(tmp_path: Path) -> None:
    path = write_catalog(tmp_path, "enabled:\n  '*': [CyclicDependency]\n")

    cfg = load_config(catalog_path=path)

    assert cfg.catalog.enabled == {"*": ("CyclicDependency",)}


def test_catalog_cannot_be_set_in_the_main_config(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"catalog\.yaml"):
        load_config(write(tmp_path, "catalog:\n  enabled: {}\n"))


@pytest.mark.parametrize(
    "text",
    [
        "enabled:\n  microservice: [SharedPersistence]\n",
        "enabled:\n  '*': [CyclicDependency, CyclicDependency]\n",
        "enabld:\n  '*': [CyclicDependency]\n",
        "- CyclicDependency\n",
    ],
    ids=["unknown-style", "duplicate-detector", "typo", "not-a-mapping"],
)
def test_invalid_catalogs_fail(tmp_path: Path, text: str) -> None:
    with pytest.raises(ConfigError):
        load_config(catalog_path=write_catalog(tmp_path, text))


def test_missing_catalog_file_fails(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="nocat.yaml"):
        load_config(catalog_path=tmp_path / "nocat.yaml")


def test_hash_changes_when_the_catalog_changes(tmp_path: Path) -> None:
    """Which detectors run changes the results, so the catalog is part of the run's hash."""
    path = write_catalog(tmp_path, "enabled:\n  '*': [CyclicDependency]\n")

    assert load_config(catalog_path=path).config_hash != C3Config().config_hash
