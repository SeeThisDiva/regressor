"""
core/series_detector.py
Series-level change-point detection and rolling baseline comparison.

Complements pairwise testing by addressing adjacent-commit dependence (where
commit C_i is both a candidate and the next baseline, creating negative p-value
dependence and letting one noisy commit poison two comparisons):
1. Rolling Baseline: compares a candidate against a pooled window of K prior commits.
2. E-Divisive Non-Parametric Change-Point Detection: uses Energy Distance between
   empirical distributions to identify structural level shifts across a full series.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from core.detector import compare_distributions, sample_cv


def rolling_baseline_compare(
    history_runs: List[List[float]],
    cand_runs: List[float],
    window_k: int = 5,
    alpha: float = 0.01,
    noise_floor_multiplier: float = 3.0,
    adjust_autocorr: bool = False,
) -> Dict[str, Any]:
    """Compare candidate commit runs against a rolling window of the last K commits.

    Pooling runs across the window prevents a single noisy commit from dominating
    and stops a persistent step shift (e.g., [A, A, B] followed by B) from
    re-flagging on subsequent commits.
    """
    if window_k < 1:
        raise ValueError("window_k must be >= 1")
    non_empty = [r for r in history_runs if len(r) > 0]
    if not non_empty:
        raise ValueError("history_runs must contain at least 1 historical commit.")

    window = non_empty[-window_k:]
    pooled_base = [val for runs in window for val in runs]

    res = compare_distributions(
        np.asarray(pooled_base, dtype=np.float64),
        np.asarray(cand_runs, dtype=np.float64),
        alpha=alpha,
        noise_floor_multiplier=noise_floor_multiplier,
        adjust_autocorr=adjust_autocorr,
    )
    res["window_size_commits"] = len(window)
    res["stable_commits_used"] = len(window)
    res["rolling_baseline_n"] = len(pooled_base)
    return res


def energy_distance_1d(a: np.ndarray, b: np.ndarray) -> float:
    """Compute 1D energy distance: ``2*E|X - Y| - E|X - X'| - E|Y - Y'|``."""
    if len(a) == 0 or len(b) == 0:
        return 0.0

    diff_ab = np.abs(a[:, None] - b[None, :]).mean()
    diff_aa = np.abs(a[:, None] - a[None, :]).mean()
    diff_bb = np.abs(b[:, None] - b[None, :]).mean()
    return float(2.0 * diff_ab - diff_aa - diff_bb)


def _pairwise_abs(x: np.ndarray) -> np.ndarray:
    """Return the n x n matrix of pairwise absolute differences ``|x_i - x_j|``."""
    return np.abs(x[:, None] - x[None, :])


def _split_stats(dist: np.ndarray, min_cluster: int) -> np.ndarray:
    """Weighted energy statistic for every admissible split tau of one ordered sample.

    ``dist`` is the n x n matrix ``|x_i - x_j|`` in series order. Using a 2-D cumulative
    sum computes all splits in O(n^2) total rather than O(n^2) per split. The statistic
    matches ``energy_distance_1d`` (V-statistic including the zero diagonal) scaled by
    ``n1 * n2 / (n1 + n2)``. Entry ``k`` corresponds to ``tau = min_cluster + k``.
    """
    n = dist.shape[0]
    integral = dist.cumsum(axis=0).cumsum(axis=1)
    total = integral[n - 1, n - 1]
    out = []
    for tau in range(min_cluster, n - min_cluster + 1):
        n1, n2 = tau, n - tau
        aa = integral[tau - 1, tau - 1]
        left_rows = integral[tau - 1, n - 1]  # rows [0, tau) x all columns
        ab = left_rows - aa                    # rows [0, tau) x cols [tau, n)
        bb = total - 2.0 * left_rows + aa      # rows/cols [tau, n)
        edist = 2.0 * ab / (n1 * n2) - aa / (n1 * n1) - bb / (n2 * n2)
        out.append((n1 * n2 / (n1 + n2)) * edist)
    return np.asarray(out)


def _scan_segment(
    commit_medians: np.ndarray,
    start_idx: int,
    end_idx: int,
    min_cluster_size: int,
    permutations: int,
    rng: np.random.Generator,
) -> Optional[Tuple[int, float, float]]:
    """Find the strongest split inside ``[start_idx, end_idx)`` and its permutation p-value."""
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
    """E-Divisive change-point detection across a full commit time series.

    For each segment, the candidate split ``tau*`` maximizes the weighted energy
    statistic. Significance is tested by comparing the observed maximum against the
    maximum over all admissible splits under random permutations of the segment
    (testing against the maximum prevents the inflated false-positive rate that occurs
    when permuting only at the chosen ``tau*``).

    Args:
        commit_shas: Ordered list of commit SHAs corresponding to ``series_runs``.
        series_runs: Per-commit lists of run medians.
        min_cluster_size: Minimum commits required on each side of a split.
        permutations: Number of random permutations per segment test.
        significance_alpha: Permutation p-value threshold to accept a split.
        seed: PRNG seed for permutation reproducibility.
        known_breaks: Optional commit indices that begin a new measurement session;
            change points at those indices are tagged ``session_break=True``.
        noise_floor_multiplier: Multiplier applied to median standard error of
            commit medians (``CV / sqrt(runs)``) for ``exceeds_noise_floor``.

    Note:
        The permutation null assumes commit medians within a stationary segment are
        exchangeable (no slow monotonic drift).
    """
    t_len = len(commit_shas)
    if t_len < 2 * min_cluster_size:
        return []

    commit_medians = np.array([float(np.median(r)) for r in series_runs], dtype=np.float64)
    # Segments compare commit medians whose noise scales as CV / sqrt(n_runs).
    ses = [sample_cv(r) / np.sqrt(len(r)) for r in series_runs if len(r) > 1 and np.mean(r) > 0]
    floor_pct = 100.0 * noise_floor_multiplier * float(np.median(ses)) if ses else 0.0
    break_set = set(known_breaks or [])

    rng = np.random.default_rng(seed)
    changepoints: List[Dict[str, Any]] = []

    def bisect(start: int, end: int) -> None:
        cand = _scan_segment(commit_medians, start, end, min_cluster_size, permutations, rng)
        if not cand:
            return
        tau, stat, p_val = cand
        if p_val > significance_alpha:
            return

        left_med = float(np.median(commit_medians[start:tau]))
        right_med = float(np.median(commit_medians[tau:end]))
        shift_pct = 100.0 * (right_med - left_med) / left_med if left_med > 0 else 0.0

        changepoints.append({
            "index": tau,
            "commit_sha": commit_shas[tau],
            "left_range": f"{commit_shas[start]}..{commit_shas[tau - 1]}",
            "right_range": f"{commit_shas[tau]}..{commit_shas[end - 1]}",
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
