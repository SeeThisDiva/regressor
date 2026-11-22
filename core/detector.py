"""
core/detector.py
Statistical change-point detection engine for performance regression testing.

- Non-parametric Mann-Whitney U test on per-run medians (robust to heavy-tail OS jitter).
- Hodges-Lehmann effect size estimator.
- Dynamic noise-floor gate (shift must exceed noise_floor_multiplier x baseline CV).
- Benjamini-Hochberg (BH) and Benjamini-Yekutieli (BY) False Discovery Rate control.
- Within-sample run-order trend and lag-1 autocorrelation diagnostics.
- Optional moving-block bootstrap p-value and canary environment cross-reference.
"""

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
from scipy import stats

TREND_RHO_SUSPECT = 0.5
NumericArray = Union[Sequence[float], np.ndarray]


def sample_std(values: NumericArray) -> float:
    """Return the Bessel-corrected (ddof=1) sample standard deviation, or 0.0 if len <= 1."""
    arr = np.asarray(values, dtype=np.float64)
    if len(arr) <= 1:
        return 0.0
    return float(np.std(arr, ddof=1))


def sample_cv(values: NumericArray) -> float:
    """Return the sample coefficient of variation (std / mean) as a fraction, or 0.0."""
    arr = np.asarray(values, dtype=np.float64)
    if len(arr) <= 1:
        return 0.0
    mean = float(np.mean(arr))
    if mean <= 0.0:
        return 0.0
    return float(np.std(arr, ddof=1)) / mean


def summarize_distribution(values: NumericArray, bins: int = 10) -> Dict[str, Any]:
    """Compute descriptive summary statistics and a histogram for per-run medians."""
    arr = np.asarray(values, dtype=np.float64)
    if len(arr) == 0:
        raise ValueError("Cannot summarize an empty sample sequence")

    mean = float(np.mean(arr))
    std = sample_std(arr)
    cv = sample_cv(arr)
    hist, edges = np.histogram(arr, bins=bins)
    return {
        "rep_count": int(len(arr)),
        "rep_medians": [round(float(x), 1) for x in arr],
        "median_ns": round(float(np.median(arr)), 1),
        "mean_ns": round(mean, 1),
        "std_ns": round(std, 1),
        "cv_pct": round(cv * 100.0, 2),
        "min_ns": round(float(arr.min()), 1),
        "max_ns": round(float(arr.max()), 1),
        "histogram": [
            {
                "bin_start_ns": round(float(edges[i]), 1),
                "bin_end_ns": round(float(edges[i + 1]), 1),
                "count": int(hist[i]),
            }
            for i in range(len(hist))
        ],
    }


def hodges_lehmann(a: np.ndarray, b: np.ndarray, max_n: int = 1000, seed: int = 0) -> float:
    """Median of all pairwise differences ``b_j - a_i`` (subsampled if N > ``max_n``)."""
    rng = np.random.default_rng(seed)
    if len(a) > max_n:
        a = rng.choice(a, size=max_n, replace=False)
    if len(b) > max_n:
        b = rng.choice(b, size=max_n, replace=False)
    diffs = b[:, None] - a[None, :]
    return float(np.median(diffs))


def order_trend(x: np.ndarray) -> Dict[str, Any]:
    """Spearman correlation of run order vs value.

    A strong trend indicates runs are not exchangeable (e.g., thermal ramp or
    co-tenant arrival), which makes Mann-Whitney p-values optimistic. Diagnostic
    only: it never changes a verdict directly.
    """
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
    """AR(1) effective sample size ``N_eff = N * (1 - r_1) / (1 + r_1)`` for positive ``r_1``.

    Quantifies how much within-commit autocorrelation reduces independent information.
    """
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    if n <= 2:
        return float(n)
    r1 = max(0.0, lag1_autocorr(x))
    n_eff = n * (1.0 - r1) / (1.0 + r1)
    return round(float(np.clip(n_eff, 2.0, float(n))), 2)


def _draw_circular_blocks(
    rng: np.random.Generator,
    pooled_blocks: Tuple[np.ndarray, np.ndarray],
    block_len: int,
    target_n: int,
) -> np.ndarray:
    """Resample contiguous circular blocks from centered residual series."""
    out: List[float] = []
    while len(out) < target_n:
        src = pooled_blocks[int(rng.integers(0, 2))]
        start = int(rng.integers(0, len(src)))
        for k in range(block_len):
            out.append(float(src[(start + k) % len(src)]))
            if len(out) == target_n:
                break
    return np.asarray(out, dtype=np.float64)


def block_bootstrap_p_value(
    baseline: np.ndarray,
    candidate: np.ndarray,
    block_len: int = 0,
    n_boot: int = 999,
    seed: int = 0,
) -> float:
    """Two-sided moving-block bootstrap p-value for the Hodges-Lehmann shift under H0.

    Centers each series around its own median while keeping contiguous blocks intact,
    preserving short-range autocorrelation and run-order drift.
    """
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

    pooled_blocks = (a - np.median(a), b - np.median(b))
    rng = np.random.default_rng(seed)
    exceed = 0
    for _ in range(n_boot):
        sim_a = _draw_circular_blocks(rng, pooled_blocks, block_len, na)
        sim_b = _draw_circular_blocks(rng, pooled_blocks, block_len, nb)
        if abs(hodges_lehmann(sim_a, sim_b)) >= obs:
            exceed += 1
    return float((exceed + 1.0) / (n_boot + 1.0))


def _classify_verdict(
    statistically_significant: bool,
    exceeds_noise_floor: bool,
    canary_shifted: bool,
    drift_suspect: bool,
) -> Tuple[str, str, str]:
    """Map statistical/noise gates and drift diagnostics to (verdict, attribution, note)."""
    if not (statistically_significant and exceeds_noise_floor):
        return (
            "ok",
            "NO_REGRESSION",
            "Shift within measured noise floor or not significant.",
        )

    if canary_shifted:
        attribution = "ENVIRONMENT_DRIFT_SUSPECTED"
        note = "Canary shifted in the same window; treat as environment until re-measured."
    else:
        attribution = "FLAGGED_LATENCY_ONLY"
        note = "Significant shift above noise floor. Needs re-measurement (ideally interleaved)."

    if drift_suspect:
        note += " Run-order trend inside a sample: p-value is optimistic, prefer interleaved re-measurement."

    return "flag", attribution, note


def compare_distributions(
    baseline: np.ndarray,
    candidate: np.ndarray,
    alpha: float = 0.01,
    noise_floor_multiplier: float = 3.0,
    canary_shifted: bool = False,
    adjust_autocorr: bool = False,
    min_noise_floor_pct: float = 0.0,
) -> Dict[str, Any]:
    """Compare baseline vs candidate distributions of independent per-run medians.

    When ``adjust_autocorr=True``, also computes a moving-block bootstrap p-value
    and takes ``max(mw_p_value, block_bootstrap_p_value)``. Under strong AR(1)
    autocorrelation, the block bootstrap only partially mitigates rank-sum optimism;
    the 3x CV noise-floor gate and interleaved A/B re-measurement remain primary
    defenses against false flags. ``min_noise_floor_pct`` optionally enforces a
    calibrated cross-build minimum noise floor (in percent) without altering
    default behavior when left at ``0.0``.
    """
    baseline = np.asarray(baseline, dtype=np.float64)
    candidate = np.asarray(candidate, dtype=np.float64)
    baseline_median = float(np.median(baseline))
    baseline_cv = sample_cv(baseline)

    _, mw_p_value = stats.mannwhitneyu(candidate, baseline, alternative="two-sided")
    shift_abs = hodges_lehmann(baseline, candidate)
    shift_pct = (100.0 * shift_abs / baseline_median) if baseline_median > 0 else 0.0

    base_trend = order_trend(baseline)
    cand_trend = order_trend(candidate)
    drift_suspect = any(
        t["rho"] is not None and abs(t["rho"]) >= TREND_RHO_SUSPECT and t["p"] < 0.01
        for t in (base_trend, cand_trend)
    )

    block_p = None
    p_value = float(mw_p_value)
    if adjust_autocorr:
        block_p = block_bootstrap_p_value(baseline, candidate)
        p_value = max(p_value, block_p)

    noise_floor_pct = max(100.0 * baseline_cv * noise_floor_multiplier, float(min_noise_floor_pct))
    statistically_significant = bool(p_value < alpha)
    exceeds_noise_floor = bool(abs(shift_pct) > noise_floor_pct)
    verdict, attribution, resolution_note = _classify_verdict(
        statistically_significant,
        exceeds_noise_floor,
        canary_shifted,
        drift_suspect,
    )

    return {
        "verdict": verdict,
        "p_value": float(p_value),
        "mann_whitney_p_value": float(mw_p_value),
        "block_bootstrap_p_value": round(float(block_p), 5) if block_p is not None else None,
        "shift_pct": round(shift_pct, 3),
        "baseline_median_ns": round(baseline_median, 1),
        "baseline_cv_pct": round(100.0 * baseline_cv, 3),
        "noise_floor_pct": round(noise_floor_pct, 3),
        "statistically_significant": statistically_significant,
        "exceeds_noise_floor": exceeds_noise_floor,
        "attribution": attribution,
        "resolution_status": "unreviewed",
        "resolution_note": resolution_note,
        "baseline_trend_rho": base_trend["rho"],
        "candidate_trend_rho": cand_trend["rho"],
        "baseline_lag1_r": round(lag1_autocorr(baseline), 3),
        "candidate_lag1_r": round(lag1_autocorr(candidate), 3),
        "effective_n_baseline": effective_sample_size(baseline),
        "effective_n_candidate": effective_sample_size(candidate),
        "drift_suspect": bool(drift_suspect),
        "n_baseline": len(baseline),
        "n_candidate": len(candidate),
    }


def compare_benchmark_runs(
    base_runs_by_bench: Mapping[str, Sequence[float]],
    cand_runs_by_bench: Mapping[str, Sequence[float]],
    benchmarks: Optional[Sequence[str]] = None,
    min_runs: int = 1,
    alpha: float = 0.01,
    noise_floor_multiplier: float = 3.0,
    adjust_autocorr: bool = False,
) -> List[Dict[str, Any]]:
    """Run ``compare_distributions`` across all matching benchmarks of two commits.

    Each returned dictionary includes a ``benchmark`` key. Benchmarks with fewer
    than ``min_runs`` samples in either commit are skipped.
    """
    names = list(benchmarks) if benchmarks is not None else sorted(set(base_runs_by_bench) | set(cand_runs_by_bench))
    results: List[Dict[str, Any]] = []
    for bench in names:
        base_runs = base_runs_by_bench.get(bench, ())
        cand_runs = cand_runs_by_bench.get(bench, ())
        if len(base_runs) < min_runs or len(cand_runs) < min_runs:
            continue
        res = compare_distributions(
            np.asarray(base_runs, dtype=np.float64),
            np.asarray(cand_runs, dtype=np.float64),
            alpha=alpha,
            noise_floor_multiplier=noise_floor_multiplier,
            adjust_autocorr=adjust_autocorr,
        )
        res["benchmark"] = bench
        results.append(res)
    return results


def bh_fdr_correct(
    comparisons: List[Dict[str, Any]],
    alpha: float = 0.05,
    method: str = "bh",
) -> List[Dict[str, Any]]:
    """Step-up FDR correction across a batch of comparisons.

    ``method="bh"``: Benjamini-Hochberg. Controls FDR at ``alpha`` for independent or
        positively dependent (PRDS) p-values.
    ``method="by"``: Benjamini-Yekutieli. Divides ``alpha`` by the harmonic number H(m),
        keeping FDR control under arbitrary dependence (including negative dependence
        between adjacent commit pairs that share a noisy intermediate commit).
    """
    if method not in ("bh", "by"):
        raise ValueError(f"unknown FDR method {method!r} (expected 'bh' or 'by')")
    m = len(comparisons)
    if m == 0:
        return comparisons

    level = alpha if method == "bh" else alpha / sum(1.0 / i for i in range(1, m + 1))

    order = sorted(range(m), key=lambda i: comparisons[i]["p_value"])
    threshold_rank = 0
    for rank, idx in enumerate(order, start=1):
        if comparisons[idx]["p_value"] <= (rank / m) * level:
            threshold_rank = rank

    for rank, idx in enumerate(order, start=1):
        comparisons[idx]["fdr_significant"] = rank <= threshold_rank

    return comparisons
