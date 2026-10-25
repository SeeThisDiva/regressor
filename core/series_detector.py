"""
core/series_detector.py
Series-level change-point detection and rolling baseline comparison.

Addresses the reviewer's insight:
Adjacent commit pairwise comparisons share a commit (C_{i-1} is cand in one, base in next),
so their p-values are not independent (violating the assumption of classical Benjamini-Hochberg).
Furthermore, one noisy baseline commit poisons two consecutive comparisons.

Implements:
1. Rolling Baseline: Compares candidate against a rolling window of K stable prior commits.
2. E-Divisive Non-Parametric Change-Point Detection (as used in MongoDB & DataStax Hunter):
   Uses Energy Distance between distributions to identify true structural change points
   across an entire sequence without pairwise independence assumptions.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from core.detector import compare_distributions


def rolling_baseline_compare(
    history_runs: List[List[float]],
    cand_runs: List[float],
    window_k: int = 5,
    alpha: float = 0.01,
    noise_floor_multiplier: float = 3.0,
    adjust_autocorr: bool = False,
) -> Dict[str, Any]:
    """
    Compares candidate commit runs against the rolling baseline of the last K commits.
    Pools the runs across the window so that a single noisy commit does not dominate
    and a persistent step shift (e.g. [A, A, B] followed by B) is not re-flagged as a new spike.
    """
    if window_k < 1:
        raise ValueError("window_k must be >= 1")
    non_empty = [r for r in history_runs if len(r) > 0]
    if not non_empty:
        raise ValueError("history_runs must contain at least 1 historical commit.")

    window = non_empty[-window_k:]
    pooled_base: List[float] = []
    for r in window:
        pooled_base.extend(r)

    arr_base = np.array(pooled_base, dtype=np.float64)
    arr_cand = np.array(cand_runs, dtype=np.float64)

    res = compare_distributions(
        arr_base,
        arr_cand,
        alpha=alpha,
        noise_floor_multiplier=noise_floor_multiplier,
        adjust_autocorr=adjust_autocorr,
    )
    res["window_size_commits"] = len(window)
    res["stable_commits_used"] = len(window)
    res["rolling_baseline_n"] = len(arr_base)
    return res


def energy_distance_1d(a: np.ndarray, b: np.ndarray) -> float:
    """
    Computes 1D energy distance between sample a and sample b.
    E(A, B) = 2*E|X - Y| - E|X - X'| - E|Y - Y'|
    """
    n = len(a)
    m = len(b)
    if n == 0 or m == 0:
        return 0.0

    diff_ab = np.abs(a[:, None] - b[None, :]).mean()
    diff_aa = np.abs(a[:, None] - a[None, :]).mean()
    diff_bb = np.abs(b[:, None] - b[None, :]).mean()

    return float(2.0 * diff_ab - diff_aa - diff_bb)


def _pairwise_abs(x: np.ndarray) -> np.ndarray:
    return np.abs(x[:, None] - x[None, :])


def _split_stats(dist: np.ndarray, min_cluster: int) -> np.ndarray:
    """Weighted energy statistic for every admissible split tau of one ordered sample.

    `dist` is the n x n matrix |x_i - x_j| for the series in its current order. Block sums
    for the left/right/cross terms come from a 2-D cumulative sum, so ALL splits cost
    O(n^2) together instead of O(n^2) each. The definition matches energy_distance_1d
    (V-statistic: means include the zero diagonal), times n1*n2/(n1+n2).
    Entry k of the result corresponds to tau = min_cluster + k.
    """
    n = dist.shape[0]
    integral = dist.cumsum(axis=0).cumsum(axis=1)
    total = integral[n - 1, n - 1]
    out = []
    for tau in range(min_cluster, n - min_cluster + 1):
        n1, n2 = tau, n - tau
        aa = integral[tau - 1, tau - 1]
        left_rows = integral[tau - 1, n - 1]            # rows [0,tau) x all columns
        ab = left_rows - aa                              # rows [0,tau) x cols [tau,n)
        bb = total - 2.0 * left_rows + aa                # rows/cols [tau,n)
        edist = 2.0 * ab / (n1 * n2) - aa / (n1 * n1) - bb / (n2 * n2)
        out.append((n1 * n2 / (n1 + n2)) * edist)
    return np.asarray(out)


def detect_series_changepoints_edivisive(
    commit_shas: List[str],
    series_runs: List[List[float]],
    min_cluster_size: int = 3,
    permutations: int = 199,
    significance_alpha: float = 0.05,
    seed: int = 42,
    known_breaks: Optional[Sequence[int]] = None,
    noise_floor_multiplier: float = 3.0,
) -> List[Dict[str, Any]]:
    """
    E-Divisive change-point detection across the entire commit time series.

    For each segment the best split tau* maximizes the weighted energy statistic. Its
    significance is a permutation test of the *maximum over all admissible splits*: the
    observed max is compared against the max obtained after shuffling the segment. (Comparing
    against the permuted statistic at the single observed tau* ignores that tau* was chosen
    by maximization and gives roughly 37% false positives on pure noise at nominal 5%.)

    known_breaks: indices of commits whose run started a new measurement session (gap since
        the previous commit's run exceeded the session threshold). A change point at such an
        index is reported with session_break=True because host drift and code changes are
        indistinguishable there.
    Every change point also carries exceeds_noise_floor: |shift| > noise_floor_multiplier x
    the median standard error of a commit median (within-commit CV / sqrt(runs)). Significant-but-tiny steps stay visible but are labelled.

    Caveat: the permutation null assumes commit medians are exchangeable (no slow drift).
    """
    t_len = len(commit_shas)
    if t_len < 2 * min_cluster_size:
        return []

    commit_medians = np.array([float(np.median(r)) for r in series_runs], dtype=np.float64)
    # Segments are compared through commit medians, whose noise is ~ CV / sqrt(n_runs), not the
    # single-run CV that the pairwise gate uses.
    ses = [np.std(r, ddof=1) / np.mean(r) / np.sqrt(len(r)) for r in series_runs if len(r) > 1 and np.mean(r) > 0]
    floor_pct = 100.0 * noise_floor_multiplier * float(np.median(ses)) if ses else 0.0
    break_set = set(known_breaks or [])

    rng = np.random.default_rng(seed)
    changepoints: List[Dict[str, Any]] = []

    def scan_range(start_idx: int, end_idx: int) -> Optional[Tuple[int, float, float]]:
        n = end_idx - start_idx
        if n < 2 * min_cluster_size:
            return None
        seg = commit_medians[start_idx:end_idx]
        dist = _pairwise_abs(seg)
        stats_obs = _split_stats(dist, min_cluster_size)
        k = int(np.argmax(stats_obs))
        best_stat = float(stats_obs[k])
        if best_stat <= 0:
            return None
        best_tau = start_idx + min_cluster_size + k

        exceed = 0
        for _ in range(permutations):
            perm = rng.permutation(n)
            if _split_stats(dist[np.ix_(perm, perm)], min_cluster_size).max() >= best_stat:
                exceed += 1
        p_value = (exceed + 1.0) / (permutations + 1.0)
        return (best_tau, best_stat, p_value)

    def bisect(start: int, end: int):
        cand = scan_range(start, end)
        if not cand:
            return
        tau, stat, p_val = cand
        if p_val <= significance_alpha:
            left_med = float(np.median(commit_medians[start:tau]))
            right_med = float(np.median(commit_medians[tau:end]))
            shift_pct = 100.0 * (right_med - left_med) / left_med if left_med > 0 else 0.0

            changepoints.append({
                "index": tau,
                "commit_sha": commit_shas[tau],
                "left_range": f"{commit_shas[start]}..{commit_shas[tau-1]}",
                "right_range": f"{commit_shas[tau]}..{commit_shas[end-1]}",
                "left_median_ns": round(left_med, 1),
                "right_median_ns": round(right_med, 1),
                "shift_pct": round(shift_pct, 2),
                "energy_stat": round(stat, 2),
                "permutation_p_value": round(p_val, 4),
                "noise_floor_pct": round(floor_pct, 2),
                "exceeds_noise_floor": bool(abs(shift_pct) > floor_pct),
                "session_break": tau in break_set,
            })

            bisect(start, tau)
            bisect(tau, end)

    bisect(0, t_len)
    changepoints.sort(key=lambda x: x["index"])
    return changepoints
