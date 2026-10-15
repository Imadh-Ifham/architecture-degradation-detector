"""C3 configuration: ``configs/default.yaml`` -> ``C3Config`` (plan Section 5).

Every threshold and statistical parameter in C3 comes from here; detectors and tests hold no
numeric constants. The models forbid unknown keys, so a typo in the YAML fails at start-up
instead of silently running with a default.

``config_hash`` is stored on every analysis run. It is computed from the validated config, not
from the file, so two files that describe the same run (different key order, comments, defaults
left out) have the same hash. Freeze the config before running evaluation systems.

The database connection is not here: it is deployment configuration (``app/core/config.py``),
and it does not change any result.

Bracketed ids ([D-07]) refer to the decision register in the plan, Section 10.
"""

import math
import re
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import Field, ValidationError, field_validator, model_validator

from app.components.degradation_detection.models import InternalModel
from app.domain.audit_entry import Verdict
from app.domain.degradation_event import TimeAxis, Worsening
from app.shared.canonical_json import content_hash

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "default.yaml"

Fraction = Annotated[float, Field(ge=0, le=1)]
Positive = Annotated[float, Field(gt=0)]
PositiveInt = Annotated[int, Field(gt=0)]


class ConfigError(ValueError):
    """The configuration file is missing, unreadable or invalid."""


# --- M1 --------------------------------------------------------------------------------------


class IngestConfig(InternalModel):
    release_line_regex: str = r"^v?\d+\.\d+\.\d+$"  # main release line only [D-06]
    max_package_bytes: PositiveInt = 20_000_000

    @field_validator("release_line_regex")
    @classmethod
    def _check_regex_compiles(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"not a valid regular expression: {exc}") from exc
        return value


class GateConfig(InternalModel):
    """Validation-confidence gate [D-07]: >= accept ACCEPTED, >= exclude DOWNWEIGHTED."""

    accept: Fraction = 0.70
    exclude: Fraction = 0.50

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        if self.exclude > self.accept:
            raise ValueError("gate.exclude must not be above gate.accept")
        return self


# --- M2 --------------------------------------------------------------------------------------


class C1PassthroughMetric(InternalModel):
    """A metric computed by C1 that C3 tests for a trend; C3 must be told which way is worse."""

    name: str = Field(pattern=r"^c1\..+")
    unit: str
    worsening: Worsening


class MetricsConfig(InternalModel):
    normalised_coupling: bool = True  # [D-04]
    c1_passthrough: tuple[C1PassthroughMetric, ...] = (  # [D-21]
        C1PassthroughMetric(name="c1.lcom", unit="lcom", worsening=Worsening.INCREASE),
    )


class HubConfig(InternalModel):
    iqr_k: Positive = 1.5


class UnstableConfig(InternalModel):
    ratio: Fraction = 0.3


class OversizedConfig(InternalModel):
    z_max: Positive = 3.5


class BigBallOfMudConfig(InternalModel):
    """Presence thresholds [D-24]. Degradation is still decided by the trend, not by these."""

    largest_scc_share_min: Fraction = 0.25
    modularity_max: float = Field(default=0.30, ge=-1, le=1)


class ModularityConfig(InternalModel):
    algorithm: Literal["greedy"] = "greedy"  # deterministic [D-27]


class DetectionConfig(InternalModel):
    hub: HubConfig = HubConfig()
    unstable: UnstableConfig = UnstableConfig()
    oversized: OversizedConfig = OversizedConfig()
    big_ball_of_mud: BigBallOfMudConfig = BigBallOfMudConfig()
    modularity: ModularityConfig = ModularityConfig()


# --- M3 --------------------------------------------------------------------------------------


class AlignWeights(InternalModel):
    name: Fraction = 0.4
    neighbours: Fraction = 0.4
    size: Fraction = 0.2

    @model_validator(mode="after")
    def _check_sum(self) -> Self:
        if not math.isclose(self.name + self.neighbours + self.size, 1.0, abs_tol=1e-9):
            raise ValueError("align.weights must sum to 1 so that similarity stays in [0, 1]")
        return self


class AlignConfig(InternalModel):
    weights: AlignWeights = AlignWeights()
    rename_min: Fraction = 0.75
    ambiguity_margin: Fraction = 0.05
    part_min: Fraction = 0.5
    split_min: Fraction = 0.5


class TrackingConfig(InternalModel):
    instance_jaccard_min: Fraction = 0.5  # [D-22]


# --- M4 --------------------------------------------------------------------------------------


class TrendConfig(InternalModel):
    alpha: float = Field(default=0.05, gt=0, lt=1)
    gate_on: Literal["q", "p"] = "q"  # [D-02]
    sidedness: Literal["two-sided"] = "two-sided"  # [D-01]
    min_releases: int = Field(default=8, ge=3)  # [D-03]
    exact_below: int = Field(default=10, ge=2)
    n_perm: PositiveInt = 20_000
    seed: int = 20261013
    time_axis: TimeAxis = TimeAxis.ORDINAL  # [D-05]
    bh_family: Literal["run"] = "run"  # [D-26]


class ChangePointConfig(InternalModel):
    """Post-PP1."""

    enabled: bool = False
    penalty_c: Positive = 2.0
    min_size: PositiveInt = 2


# --- M5 to M7 (post-PP1) ---------------------------------------------------------------------


class ContextConfig(InternalModel):
    enabled: bool = False  # False is the trend-only baseline [D-28]
    buffer_days: int = Field(default=90, ge=0)
    strict: bool = False


class RetrievalConfig(InternalModel):
    mode: Literal["dense", "hybrid"] = "dense"  # [D-13]
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_revision: str | None = None  # pinned when M5 is built
    chunk_tokens: PositiveInt = 280
    chunk_overlap: int = Field(default=50, ge=0)
    top_k: PositiveInt = 6
    min_score: Fraction = 0.35


class LlmConfig(InternalModel):
    provider: Literal["anthropic", "openai_compatible", "replay"] = "anthropic"  # [D-12]
    model: str | None = None  # pinned when M5 is built
    temperature: float = Field(default=0.0, ge=0)
    max_tokens: PositiveInt = 600
    prompt_version: str = "classify_v1"
    cache_mode: Literal["record", "replay"] = "record"
    timeout_s: Positive = 60
    max_retries: int = Field(default=3, ge=0)
    max_calls_per_run: PositiveInt = 500


class ReviewConfig(InternalModel):
    note_required_for: tuple[Verdict, ...] = (Verdict.REJECTED, Verdict.NEEDS_INVESTIGATION)
    note_min_chars: int = Field(default=10, ge=0)  # [D-19]


class EvalConfig(InternalModel):
    mode: bool = False  # [D-16]


# --- root ------------------------------------------------------------------------------------


class C3Config(InternalModel):
    schema_version: str = Field(default="1.1.0", pattern=r"^1\.\d+\.\d+$")
    ingest: IngestConfig = IngestConfig()
    gate: GateConfig = GateConfig()
    metrics: MetricsConfig = MetricsConfig()
    detection: DetectionConfig = DetectionConfig()
    align: AlignConfig = AlignConfig()
    tracking: TrackingConfig = TrackingConfig()
    trend: TrendConfig = TrendConfig()
    cp: ChangePointConfig = ChangePointConfig()
    context: ContextConfig = ContextConfig()
    retrieval: RetrievalConfig = RetrievalConfig()
    llm: LlmConfig = LlmConfig()
    review: ReviewConfig = ReviewConfig()
    eval: EvalConfig = EvalConfig()

    @property
    def config_hash(self) -> str:
        """``sha256:<hex>`` of the whole config; equal hash means an identically configured run."""
        return content_hash(self.model_dump(mode="json"))


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> C3Config:
    """Read and validate a YAML config file. Keys the file leaves out take their defaults."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"config {path} is not valid YAML: {exc}") from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError(f"config {path} must be a mapping of sections, not {type(raw).__name__}")
    try:
        return C3Config.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"config {path} is invalid: {exc}") from exc
