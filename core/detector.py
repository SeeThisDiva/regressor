"""
core/detector.py
Statistical change-point detection engine for performance regression testing.
- Non-parametric Mann-Whitney U test on per-run medians (robust to OS heavy-tail jitter).
- Hodges-Lehmann effect size estimator.
- Dynamic noise-floor gate (shift must exceed noise_floor_multiplier x baseline CV).
- Benjamini-Hochberg (BH) False Discovery Rate control across batches.
- Optional canary cross-reference (environment drift).
"""

from typing import Any, Dict, List

import numpy as np
from scipy import stats


def hodges_lehmann(a: np.ndarray, b: np.ndarray, max_n: int = 1000, seed: int = 0) -> float:
    """Median of all pairwise differences b_j - a_i (subsampled if N > max_n)."""
    rng = np.random.default_rng(seed)
    if len(a) > max_n:
        a = rng.choice(a, size=max_n, replace=False)
    if len(b) > max_n:
        b = rng.choice(b, size=max_n, replace=False)
    diffs = b[:, None] - a[None, :]
    return float(np.median(diffs))


def order_trend(x: np.ndarray) -> Dict[str, Any]:
    """Spearman correlation of run order vs value. A strong trend means runs are not
    exchangeable (thermal ramp, co-tenant arrival), which makes Mann-Whitney p-values
    optimistic. Diagnostic only: it never changes a verdict."""
    x = np.asarray(x, dtype=np.float64)
    if len(x) < 8 or np.ptp(x) == 0:
        return {"rho": None, "p": None}
    rho, p = stats.spearmanr(np.arange(len(x)), x)
    return {"rho": round(float(rho), 3), "p": float(p)}


def lag1_autocorr(x: np.ndarray) -> float:
    """Lag-1 sample autocorrelation r_1. Returns 0.0 if constant or too short."""
    x = np.asarray(x, dtype=np.float64)
    if len(x) < 4:
        return 0.0
    centered = x - np.mean(x)
    denom = float(np.dot(centered, centered))
    if denom <= 0.0:
        return 0.0
    r1 = float(np.dot(centered[:-1], centered[1:]) / denom)
    return float(np.clip(r1, -0.99, 0.99))


def effective_sample_size(x: np.ndarray) -> float:
    """AR(1) effective sample size N_eff = N * (1 - r_1) / (1 + r_1) for positive r_1.
    Quantifies how much within-commit autocorrelation reduces independent information."""
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    if n <= 2:
        return float(n)
    r1 = max(0.0, lag1_autocorr(x))
    n_eff = n * (1.0 - r1) / (1.0 + r1)
    return round(float(np.clip(n_eff, 2.0, float(n))), 2)


def block_bootstrap_p_value(
    baseline: np.ndarray,
    candidate: np.ndarray,
    block_len: int = 0,
    n_boot: int = 999,
    seed: int = 0,
) -> float:
    """Two-sided moving-block bootstrap p-value for the Hodges-Lehmann shift under H0.
    Centers both series to their common median while keeping contiguous blocks intact,
    preserving short-range autocorrelation and run-order drift."""
    a = np.asarray(baseline, dtype=np.float64)
    b = np.asarray(candidate, dtype=np.float64)
    na, nb = len(a), len(b)
    if na < 4 or nb < 4:
        return 1.0
    obs = abs(hodges_lehmann(a, b))
    if obs == 0.0:
        return 1.0

    if block_len <= 0:
        block_len = max(2, int(round(max(na, nb) ** (1.0 / 3.0))))

    # Center each series around its own median to form the null residuals with intact autocorrelation
    res_a = a - np.median(a)
    res_b = b - np.median(b)
    pooled_blocks = (res_a, res_b)
    rng = np.random.default_rng(seed)

    def draw_series(target_n: int) -> np.ndarray:
        out: List[float] = []
        while len(out) < target_n:
            src = pooled_blocks[int(rng.integers(0, 2))]
            start = int(rng.integers(0, len(src)))
            for k in range(block_len):
                out.append(float(src[(start + k) % len(src)]))
                if len(out) == target_n:
                    break
        return np.asarray(out, dtype=np.float64)

    exceed = 0
    for _ in range(n_boot):
        sim_a = draw_series(na)
        sim_b = draw_series(nb)
        if abs(hodges_lehmann(sim_a, sim_b)) >= obs:
            exceed += 1
    return float((exceed + 1.0) / (n_boot + 1.0))


TREND_RHO_SUSPECT = 0.5


def compare_distributions(
    baseline: np.ndarray,
    candidate: np.ndarray,
    alpha: float = 0.01,
    noise_floor_multiplier: float = 3.0,
    canary_shifted: bool = False,
    adjust_autocorr: bool = False,
) -> Dict[str, Any]:
    """
    Compare baseline vs candidate distributions of independent per-run medians.
    When `adjust_autocorr=True`, computes a moving-block bootstrap p-value alongside
    Mann-Whitney. Note: under strong AR(1) autocorrelation (e.g. phi=0.4..0.7), the
    block bootstrap only partially reduces Mann-Whitney's inflated false-positive rate
    (e.g. 7.7% -> 5.3% at phi=0.4, 27% -> 20% at phi=0.7); it is the 3xCV noise-floor
    gate and interleaved A/B re-measurement that prevent false flags in practice.
    Default (`adjust_autocorr=False`) preserves the exact rank-sum test from the baseline study.
    """
    baseline = np.asarray(baseline, dtype=np.float64)
    candidate = np.asarray(candidate, dtype=np.float64)
    baseline_median = float(np.median(baseline))
    baseline_mean = float(np.mean(baseline))
    baseline_std = float(np.std(baseline, ddof=1)) if len(baseline) > 1 else float(np.std(baseline))
    baseline_cv = (baseline_std / baseline_mean) if baseline_mean > 0 else 0.0

    u_stat, mw_p_value = stats.mannwhitneyu(candidate, baseline, alternative="two-sided")
    shift_abs = hodges_lehmann(baseline, candidate)
    shift_pct = (100.0 * shift_abs / baseline_median) if baseline_median > 0 else 0.0

    base_trend = order_trend(baseline)
    cand_trend = order_trend(candidate)
    base_r1 = round(lag1_autocorr(baseline), 3)
    cand_r1 = round(lag1_autocorr(candidate), 3)
    n_eff_base = effective_sample_size(baseline)
    n_eff_cand = effective_sample_size(candidate)
    drift_suspect = any(t["rho"] is not None and abs(t["rho"]) >= TREND_RHO_SUSPECT and t["p"] < 0.01
                        for t in (base_trend, cand_trend))

    block_p = None
    p_value = float(mw_p_value)
    if adjust_autocorr:
        block_p = block_bootstrap_p_value(baseline, candidate)
        p_value = max(p_value, block_p)

    noise_floor_pct = 100.0 * baseline_cv * noise_floor_multiplier
    statistically_significant = bool(p_value < alpha)
    exceeds_noise_floor = bool(abs(shift_pct) > noise_floor_pct)

    verdict = "flag" if (statistically_significant and exceeds_noise_floor) else "ok"

    if verdict == "flag" and canary_shifted:
        attribution = "ENVIRONMENT_DRIFT_SUSPECTED"
        resolution_note = "Canary shifted in the same window; treat as environment until re-measured."
    elif verdict == "flag":
        attribution = "FLAGGED_LATENCY_ONLY"
        resolution_note = "Significant shift above noise floor. Needs re-measurement (ideally interleaved)."
    else:
        attribution = "NO_REGRESSION"
        resolution_note = "Shift within measured noise floor or not significant."
    resolution_status = "unreviewed"

    if verdict == "flag" and drift_suspect:
        resolution_note += " Run-order trend inside a sample: p-value is optimistic, prefer interleaved re-measurement."

    return {
        "verdict": verdict,
        "p_value": float(p_value),
        "mann_whitney_p_value": float(mw_p_value),
        "block_bootstrap_p_value": round(float(block_p), 5) if block_p is not None else None,
        "shift_pct": round(shift_pct, 3),
        "baseline_median_ns": round(baseline_median, 1),
        "baseline_cv_pct": round(100 * baseline_cv, 3),
        "noise_floor_pct": round(noise_floor_pct, 3),
        "statistically_significant": statistically_significant,
        "exceeds_noise_floor": exceeds_noise_floor,
        "attribution": attribution,
        "resolution_status": resolution_status,
        "resolution_note": resolution_note,
        "baseline_trend_rho": base_trend["rho"],
        "candidate_trend_rho": cand_trend["rho"],
        "baseline_lag1_r": base_r1,
        "candidate_lag1_r": cand_r1,
        "effective_n_baseline": n_eff_base,
        "effective_n_candidate": n_eff_cand,
        "drift_suspect": bool(drift_suspect),
        "n_baseline": len(baseline),
        "n_candidate": len(candidate),
    }


def bh_fdr_correct(comparisons: List[Dict[str, Any]], alpha: float = 0.05, method: str = "bh") -> List[Dict[str, Any]]:
    """
    Step-up FDR correction across a batch of comparisons.

    method="bh": Benjamini-Hochberg. Controls FDR at `alpha` for independent or positively
        dependent (PRDS) p-values.
    method="by": Benjamini-Yekutieli. Divides alpha by the harmonic number H(m), which keeps FDR
        control under arbitrary dependence. Use it for adjacent-commit batches: commit C_i is the
        candidate in one comparison and the baseline in the next, so a noisy C_i pushes the two
        shifts in opposite directions (negative dependence, which BH does not cover).
    """
    if method not in ("bh", "by"):
        raise ValueError(f"unknown FDR method {method!r} (expected 'bh' or 'by')")
    m = len(comparisons)
    if m == 0:
        return comparisons

    level = alpha
    if method == "by":
        level = alpha / sum(1.0 / i for i in range(1, m + 1))

    order = sorted(range(m), key=lambda i: comparisons[i]["p_value"])
    threshold_rank = 0
    for rank, idx in enumerate(order, start=1):
        if comparisons[idx]["p_value"] <= (rank / m) * level:
            threshold_rank = rank

    for rank, idx in enumerate(order, start=1):
        comparisons[idx]["fdr_significant"] = rank <= threshold_rank

    return comparisons
