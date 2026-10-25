"""
core/interleaved.py
Interleaved A/B benchmarking of two builds with a paired Wilcoxon signed-rank test.

Why: every false positive in the legacy study came from comparing runs taken
minutes-to-hours apart. Sequential designs (all A, then all B) let host drift
masquerade as a code change. Here both builds run in alternation inside the same
time window, and each pair is compared only with itself:

    pair k:  run A_k and B_k back to back (order randomized per pair)
    d_k   =  100 * (median(B_k) - median(A_k)) / median(A_k)

Slow drift (thermal state, co-tenants, frequency) hits A_k and B_k almost equally,
so it largely cancels in d_k. Randomizing which build goes first in each pair
prevents a systematic "second run is warmer/colder" bias.

Decision rule: flag iff the Wilcoxon signed-rank test rejects zero shift at
`alpha` AND the Hodges-Lehmann estimate of the paired shift exceeds
`min_effect_pct` (a practical-significance threshold).
"""

import time
from typing import Any, Dict, List, Optional

import numpy as np
from scipy import stats

from adapters.base import BaseAdapter


def min_wilcoxon_p(n: int) -> float:
    """Smallest two-sided p-value the exact Wilcoxon test can produce with n pairs."""
    return 2.0 / (2 ** n)


def walsh_hodges_lehmann(d: np.ndarray) -> float:
    """One-sample Hodges-Lehmann estimator: median of all Walsh averages (d_i + d_j)/2, i <= j.
    This is the location estimate that matches the Wilcoxon signed-rank test."""
    i, j = np.triu_indices(len(d))
    return float(np.median((d[i] + d[j]) / 2.0))


def bootstrap_ci(d: np.ndarray, n_boot: int = 2000, level: float = 0.95, seed: int = 0) -> List[float]:
    rng = np.random.default_rng(seed)
    est = [walsh_hodges_lehmann(rng.choice(d, size=len(d), replace=True)) for _ in range(n_boot)]
    lo, hi = np.percentile(est, [(1 - level) / 2 * 100, (1 + level) / 2 * 100])
    return [round(float(lo), 3), round(float(hi), 3)]


def analyze_paired(
    a_medians: List[float],
    b_medians: List[float],
    alpha: float = 0.01,
    min_effect_pct: float = 1.0,
    require_ci_bound: bool = False,
) -> Dict[str, Any]:
    """Statistics on already-collected interleaved pairs (pure function, easy to test)."""
    a = np.asarray(a_medians, dtype=np.float64)
    b = np.asarray(b_medians, dtype=np.float64)
    if a.shape != b.shape or len(a) < 2:
        raise ValueError("need two equal-length lists with at least 2 pairs")
    if not (np.all(np.isfinite(a)) and np.all(np.isfinite(b)) and np.all(a > 0) and np.all(b > 0)):
        raise ValueError("paired medians must be finite and strictly positive (> 0)")
    d = 100.0 * (b - a) / a

    nonzero = d[d != 0]
    if len(nonzero) == 0:
        stat, p = 0.0, 1.0
    else:
        stat, p = stats.wilcoxon(d, alternative="two-sided", zero_method="wilcox")
    hl = walsh_hodges_lehmann(d)
    ci = bootstrap_ci(d)

    significant = bool(p < alpha)
    ci_clears = bool((hl > 0 and ci[0] > min_effect_pct) or (hl < 0 and ci[1] < -min_effect_pct))
    practical = ci_clears if require_ci_bound else bool(abs(hl) > min_effect_pct)
    # The exact test drops zero differences, so its resolution depends on the non-zero pairs.
    # When p sits at that floor, every non-zero pair moved the same way: p cannot grade the
    # evidence any further, and reports should say so instead of quoting it as "stronger".
    n_nonzero = int(len(nonzero))
    min_p = min_wilcoxon_p(n_nonzero) if n_nonzero else 1.0
    p_at_floor = bool(n_nonzero > 0 and p <= min_p * (1.0 + 1e-6))
    return {
        "pairs": int(len(d)),
        "paired_diffs_pct": [round(float(x), 3) for x in d],
        "baseline_median_ns": round(float(np.median(a)), 1),
        "candidate_median_ns": round(float(np.median(b)), 1),
        "shift_pct": round(hl, 3),
        "shift_ci95_pct": ci,
        "ci_clears_min_effect": ci_clears,
        "wilcoxon_stat": float(stat),
        "p_value": float(p),
        "alpha": alpha,
        "min_effect_pct": min_effect_pct,
        "require_ci_bound": bool(require_ci_bound),
        "nonzero_pairs": n_nonzero,
        "min_achievable_p": min_p,
        "p_at_floor": p_at_floor,
        "verdict": "flag" if (significant and practical) else "ok",
    }


def run_interleaved(
    adapter: BaseAdapter,
    bench_name: str,
    artifact_a: Optional[str],
    artifact_b: Optional[str],
    pairs: int = 20,
    iters: int = 1500,
    warmup: int = 150,
    inject_ns_b: int = 0,
    alpha: float = 0.01,
    min_effect_pct: float = 1.0,
    seed: Optional[int] = None,
    require_ci_bound: bool = False,
) -> Dict[str, Any]:
    """Run `pairs` interleaved (A, B) process pairs and analyze the paired differences."""
    if min_wilcoxon_p(pairs) >= alpha:
        raise ValueError(
            f"{pairs} pairs can never reach p < {alpha} with an exact Wilcoxon test "
            f"(minimum p = {min_wilcoxon_p(pairs):.4f}). Use more pairs."
        )
    rng = np.random.default_rng(seed)
    a_meds: List[float] = []
    b_meds: List[float] = []
    order: List[str] = []
    t_start = time.time()

    for _ in range(pairs):
        a_first = bool(rng.random() < 0.5)
        runs = {}
        for which in (("A", "B") if a_first else ("B", "A")):
            art = artifact_a if which == "A" else artifact_b
            inj = 0 if which == "A" else inject_ns_b
            runs[which] = float(np.median(adapter.run(bench_name, iters, warmup, inject_ns=inj, artifact=art)))
        a_meds.append(runs["A"])
        b_meds.append(runs["B"])
        order.append("AB" if a_first else "BA")

    res = analyze_paired(a_meds, b_meds, alpha=alpha, min_effect_pct=min_effect_pct,
                         require_ci_bound=require_ci_bound)

    # Order-effect diagnostic: if the second run in a pair is systematically
    # slower/faster, AB and BA pairs will disagree.
    d = np.array(res["paired_diffs_pct"])
    ab = d[[o == "AB" for o in order]]
    ba = d[[o == "BA" for o in order]]
    res.update({
        "benchmark": bench_name,
        "artifact_a": artifact_a,
        "artifact_b": artifact_b,
        "inject_ns_b": inject_ns_b,
        "order": order,
        "order_effect_pct": round(float(np.median(ab) - np.median(ba)), 3) if len(ab) and len(ba) else None,
        "wall_seconds": round(time.time() - t_start, 1),
        "a_medians": [round(x, 1) for x in a_meds],
        "b_medians": [round(x, 1) for x in b_meds],
    })
    return res
