"""Mann-Kendall trend test, self-implemented (locked decision 8; pure).

``S = sum(sign(x_j - x_i) for i < j)``: positive when later values tend to be larger. The test
uses only the order of the values, so it needs no distributional assumption and one outlier
moves S by at most n - 1.

The two-sided p-value [D-01] comes from the method the series calls for:

- **DEGENERATE** - every value equal: no ordering information at all, p = 1.
- **EXACT** - n < ``exact_below`` and no ties: ``P(|S| >= |s|)`` from the Mahonian
  distribution (``exact_dist``). A normal approximation is poor for so few points.
- **PERMUTATION** - n < ``exact_below`` with ties: the Mahonian table assumes distinct values,
  and ties shrink the real spread of S, so the observed values are shuffled ``n_perm`` times with
  a fixed seed instead. ``p = (hits + 1) / (n_perm + 1)``, which is never 0.
- **NORMAL** - n >= ``exact_below``: S is close to normal with
  ``Var(S) = [n(n-1)(2n+5) - sum t(t-1)(2t+5)] / 18`` (t = size of each tie group), and z gets a
  continuity correction of 1 towards 0 because S moves in steps of 2.

Ties mean exact float equality, as in the oracles (``scipy``, ``pymannkendall``). The input has
no nulls: the analyzer drops null points first, MK needs only their order.
"""

import math
from collections import Counter
from collections.abc import Sequence

import numpy as np

from app.components.degradation_detection.trends.exact_dist import exact_two_sided_p
from app.components.degradation_detection.trends.models import MannKendallResult
from app.domain.degradation_event import TestMethod


def kendall_s(values: Sequence[float]) -> int:
    """Concordant minus discordant pairs; a tied pair counts 0."""
    return sum(
        (later > earlier) - (later < earlier)
        for i, earlier in enumerate(values)
        for later in values[i + 1 :]
    )


def permutation_p(values: Sequence[float], s: int, *, n_perm: int, seed: int) -> float:
    """Two-sided p of ``s`` from ``n_perm`` seeded shuffles of the observed values.

    Each call starts its own generator from ``seed``, so a series' p does not depend on which
    other series were tested before it. Reproducible for a numpy version (pinned by uv.lock).
    """
    data = np.asarray(values, dtype=float)
    n = len(data)
    rng = np.random.default_rng(seed)
    orders = rng.permuted(np.tile(np.arange(n), (n_perm, 1)), axis=1)
    shuffled = data[orders]
    earlier, later = np.triu_indices(n, k=1)
    s_perm = np.sign(shuffled[:, later] - shuffled[:, earlier]).sum(axis=1)
    hits = int(np.count_nonzero(np.abs(s_perm) >= abs(s)))
    return (hits + 1) / (n_perm + 1)


def mann_kendall(
    values: Sequence[float], *, exact_below: int, n_perm: int, seed: int
) -> MannKendallResult:
    data = [float(value) for value in values]
    n = len(data)
    if n < 2:
        raise ValueError(f"Mann-Kendall needs at least 2 values, got {n}")
    if not all(math.isfinite(value) for value in data):
        raise ValueError("Mann-Kendall values must be finite (drop nulls before testing)")

    ties = [size for size in Counter(data).values() if size > 1]
    if ties == [n]:
        return MannKendallResult(n=n, s=0, tau=0.0, p_value=1.0, method=TestMethod.DEGENERATE)

    s = kendall_s(data)
    pairs = n * (n - 1) // 2
    tied_pairs = sum(size * (size - 1) // 2 for size in ties)
    # tau-b: the time axis has no ties, so only the values' tied pairs leave the denominator.
    tau_b = s / math.sqrt(pairs * (pairs - tied_pairs))

    var_s: float | None = None
    z: float | None = None
    if n >= exact_below:
        method = TestMethod.NORMAL
        var_s = (n * (n - 1) * (2 * n + 5) - sum(t * (t - 1) * (2 * t + 5) for t in ties)) / 18
        z = (s - math.copysign(1, s)) / math.sqrt(var_s) if s else 0.0
        p = min(math.erfc(abs(z) / math.sqrt(2)), 1.0)  # 2 * (1 - Phi(|z|)), no scipy.stats
    elif ties:
        method = TestMethod.PERMUTATION
        p = permutation_p(data, s, n_perm=n_perm, seed=seed)
    else:
        method = TestMethod.EXACT
        p = exact_two_sided_p(n, s)
    return MannKendallResult(
        n=n, s=s, var_s=var_s, z=z, tau=s / pairs, tau_b=tau_b, p_value=p, method=method
    )
