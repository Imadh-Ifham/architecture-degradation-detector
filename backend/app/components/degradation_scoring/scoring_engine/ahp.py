# AHP: criterion weights from a reciprocal pairwise matrix (principal eigenvector), Saaty's
# consistency ratio, and proportional renormalisation over the active criteria.

from collections.abc import Mapping, Sequence
from fractions import Fraction
from pathlib import Path

import numpy as np
import structlog
from pydantic import ValidationError

from app.components.degradation_scoring.scoring_engine.errors import (
    InconsistentJudgementsError,
    InvalidJudgementsError,
)
from app.components.degradation_scoring.scoring_engine.models import (
    AhpResult,
    CriterionWeights,
    PairwiseJudgements,
)
from app.domain.severity_report import Dimension

log = structlog.get_logger(__name__)

WEIGHTS_DIR = Path(__file__).resolve().parent / "weights"

# Saaty (1980) random index: mean CI of random reciprocal matrices of size n.
# n <= 2 is always perfectly consistent, so RI = 0 and CR is defined as 0 (C4-ADR-014).
RANDOM_INDEX = {
    1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49,
}  # fmt: skip
SAATY_SCALE = frozenset(Fraction(v) for v in range(1, 10)) | frozenset(
    Fraction(1, v) for v in range(2, 10)
)


def parse_matrix(cells: Sequence[Sequence[str]]) -> list[list[Fraction]]:
    # "1/3" -> Fraction(1, 3), exact, so reciprocity can be checked without rounding
    try:
        return [[Fraction(cell) for cell in row] for row in cells]
    except (ValueError, ZeroDivisionError) as error:
        raise InvalidJudgementsError(f"matrix cell is not a number: {error}") from error


def check_matrix(matrix: Sequence[Sequence[Fraction]]) -> None:
    # square, size 1..10, diagonal 1, every cell on the Saaty scale, P[j][i] = 1 / P[i][j]
    n = len(matrix)
    if n not in RANDOM_INDEX or any(len(row) != n for row in matrix):
        raise InvalidJudgementsError(f"matrix must be square with 1 to 10 rows, got {n} rows")
    for i in range(n):
        if matrix[i][i] != 1:
            raise InvalidJudgementsError(f"diagonal cell [{i}][{i}] must be 1")
        for j in range(n):
            if matrix[i][j] not in SAATY_SCALE:
                raise InvalidJudgementsError(f"cell [{i}][{j}] = {matrix[i][j]} is off the scale")
            if matrix[i][j] * matrix[j][i] != 1:
                raise InvalidJudgementsError(f"cells [{i}][{j}] and [{j}][{i}] not reciprocal")


def principal_weights(matrix: Sequence[Sequence[Fraction]]) -> AhpResult:
    # w = principal eigenvector (real part, abs, sum 1); CI = (lambda_max - n) / (n - 1),
    # CR = CI / RI(n). CI is clamped at 0: rounding can put lambda_max a hair below n.
    check_matrix(matrix)
    n = len(matrix)
    values, vectors = np.linalg.eig(np.array(matrix, dtype=float))
    k = int(np.argmax(values.real))
    vector = np.abs(vectors[:, k].real)
    lambda_max = float(values.real[k])
    ci = max((lambda_max - n) / (n - 1), 0.0) if n > 1 else 0.0
    cr = ci / RANDOM_INDEX[n] if RANDOM_INDEX[n] else 0.0
    return AhpResult(
        weights=[float(w) for w in vector / vector.sum()],
        lambda_max=lambda_max,
        consistency_index=ci,
        consistency_ratio=cr,
    )


def check_consistency(result: AhpResult, max_consistency_ratio: float) -> None:
    # Saaty's rule: CR above the maximum (0.10) means the judgements contradict each other
    if result.consistency_ratio > max_consistency_ratio:
        raise InconsistentJudgementsError(
            f"CR = {result.consistency_ratio:.3f} > {max_consistency_ratio}: revise the judgements"
        )


def renormalise(
    weights: Mapping[Dimension, float], active: Sequence[Dimension]
) -> dict[Dimension, float]:
    # w_j / sum of active w over active criteria, 0 for inactive ones; report order
    if not active:
        raise ValueError("at least one criterion must be active")
    total = sum(weights[d] for d in active)
    return {d: weights[d] / total if d in active else 0.0 for d in Dimension}


def load_judgements(version: str, directory: Path = WEIGHTS_DIR) -> PairwiseJudgements:
    path = directory / f"{version}.json"
    try:
        judgements = PairwiseJudgements.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise InvalidJudgementsError(f"cannot load AHP weights {path}: {error}") from error
    if judgements.version != version:
        raise InvalidJudgementsError(f"{path} declares version {judgements.version}")
    return judgements


def derive_weights(
    judgements: PairwiseJudgements,
    active: Sequence[Dimension],
    *,
    max_consistency_ratio: float,
) -> CriterionWeights:
    # AHP over all four criteria (one judgement set, one CR), then the inactive criteria
    # are dropped by proportional renormalisation (C4-ADR-014)
    result = principal_weights(parse_matrix(judgements.matrix))
    check_consistency(result, max_consistency_ratio)
    by_criterion = dict(zip(judgements.criteria, result.weights, strict=True))
    elicited = {d: by_criterion[d] for d in Dimension}
    active_criteria = [d for d in Dimension if d in active]
    weights = renormalise(elicited, active_criteria)
    log.info(
        "ahp_weights",
        reason="ahp_weights",
        version=judgements.version,
        provenance=judgements.provenance.value,
        consistency_ratio=round(result.consistency_ratio, 4),
        inactive=[d.value for d in Dimension if d not in active_criteria],
    )
    return CriterionWeights(
        version=judgements.version,
        provenance=judgements.provenance,
        elicited_by=judgements.elicited_by,
        lambda_max=result.lambda_max,
        consistency_index=result.consistency_index,
        consistency_ratio=result.consistency_ratio,
        active_criteria=active_criteria,
        elicited=elicited,
        weights=weights,
    )
