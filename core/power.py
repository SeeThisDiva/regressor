"""
core/power.py
Empirical false-positive rate (measured three ways) and statistical power curves.

1. Within-session A/A, random split: same commit, same session, runs shuffled.
   Measures FPR when the only noise is run-to-run jitter.
2. Within-session A/A, contiguous split: first half vs second half of one session.
   Captures slow drift within a single measurement session.
3. Real null transitions: adjacent commits whose candidate is documentation-only
   (subject matching ``doc:`` / ``docs:``), including drift across session breaks.

Power is estimated by resampling real within-session runs without replacement and
scaling the candidate sample.
"""

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
from scipy import stats

from core.detector import compare_distributions
from core.samples import read_sample_median
from core.session import SESSION_BREAK_MIN, is_session_break

NULL_SUBJECT = re.compile(r"^(doc|docs)(\(.*\))?:", re.IGNORECASE)


def binom_ci(k: int, n: int, level: float = 0.95) -> List[float]:
    """Exact (Clopper-Pearson) confidence interval for a proportion, in percent."""
    if n == 0:
        return [0.0, 100.0]
    ci = stats.binomtest(k, n).proportion_ci(confidence_level=level, method="exact")
    return [round(100 * ci.low, 2), round(100 * ci.high, 2)]


def load_session_medians(session_dir: Path, benches: Iterable[str]) -> Dict[str, List[float]]:
    """Load per-run medians from a single-session study directory, in run order."""
    out: Dict[str, List[float]] = {}
    root = Path(session_dir)
    for bench in benches:
        meds = [read_sample_median(f) for f in sorted(root.glob(f"{bench}_rep*.txt"))]
        if meds:
            out[bench] = meds
    return out


def _resample_flag_count(
    rng: np.random.Generator,
    values: np.ndarray,
    n: int,
    trials: int,
    alpha: float,
    scale: float = 1.0,
) -> int:
    """Draw ``trials`` disjoint (base, cand) splits without replacement and count flags."""
    flags = 0
    for _ in range(trials):
        perm = rng.permutation(values)
        base = perm[:n]
        cand = perm[n:2 * n] * scale if scale != 1.0 else perm[n:2 * n]
        if compare_distributions(base, cand, alpha=alpha)["verdict"] == "flag":
            flags += 1
    return flags


def aa_random_split(
    medians: List[float],
    trials: int = 1000,
    alpha: float = 0.01,
    seed: int = 42,
) -> Dict[str, Any]:
    """Shuffle a session's runs and split them in half ``trials`` times (without replacement)."""
    rng = np.random.default_rng(seed)
    x = np.asarray(medians, dtype=np.float64)
    half = len(x) // 2
    flags = _resample_flag_count(rng, x, half, trials, alpha)
    return {
        "trials": trials,
        "flags": flags,
        "fpr_pct": round(100 * flags / trials, 2),
        "ci95_pct": binom_ci(flags, trials),
    }


def aa_contiguous_split(medians: List[float], alpha: float = 0.01) -> Dict[str, Any]:
    """Compare the first half of a session against the second half (within-session drift)."""
    x = np.asarray(medians, dtype=np.float64)
    half = len(x) // 2
    r = compare_distributions(x[:half], x[half:2 * half], alpha=alpha)
    return {
        "verdict": r["verdict"],
        "shift_pct": r["shift_pct"],
        "p_value": r["p_value"],
        "noise_floor_pct": r["noise_floor_pct"],
    }


def _summarize_null_bucket(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    k = sum(1 for c in rows if c["verdict"] == "flag" and c["fdr_significant"])
    return {
        "n": len(rows),
        "flags": k,
        "fpr_pct": round(100 * k / len(rows), 2) if rows else 0.0,
        "ci95_pct": binom_ci(k, len(rows)),
    }


def null_transition_fpr(
    comparisons: List[Dict[str, Any]],
    gap_threshold_min: float = SESSION_BREAK_MIN,
) -> Dict[str, Any]:
    """Compute FPR over adjacent comparisons whose candidate commit is documentation-only.

    ``comparisons`` rows must contain: ``cand_subject``, ``verdict``, ``fdr_significant``,
    ``session_gap_min``, ``benchmark``, ``cand_sha``, and ``shift_pct``.
    """
    null = [c for c in comparisons if NULL_SUBJECT.match(c["cand_subject"] or "")]
    within = [
        c
        for c in null
        if c["session_gap_min"] is not None and not is_session_break(c["session_gap_min"], gap_threshold_min)
    ]
    across = [c for c in null if is_session_break(c["session_gap_min"], gap_threshold_min)]
    return {
        "all": _summarize_null_bucket(null),
        "within_session": _summarize_null_bucket(within),
        "across_session_break": _summarize_null_bucket(across),
        "null_commits": sorted({c["cand_sha"] for c in null}),
        "flagged": [
            {
                "cand_sha": c["cand_sha"],
                "benchmark": c["benchmark"],
                "shift_pct": round(c["shift_pct"], 2),
                "session_gap_min": c["session_gap_min"],
            }
            for c in null
            if c["verdict"] == "flag" and c["fdr_significant"]
        ],
    }


def evaluate_power_curve(
    pool: List[float],
    effect_sizes_pct: Iterable[float] = (1.0, 2.0, 3.0, 5.0, 8.0, 10.0, 15.0),
    rep_counts: Iterable[int] = (5, 10, 15, 20, 25),
    trials_per_point: int = 300,
    alpha: float = 0.01,
    seed: int = 42,
) -> Dict[str, Any]:
    """Estimate detection power ``P(flag | true slowdown = delta)`` by resampling ``pool``."""
    rng = np.random.default_rng(seed)
    x = np.asarray(pool, dtype=np.float64)
    grid: Dict[str, Dict[str, float]] = {}
    mde: Dict[str, Optional[float]] = {}

    for n in rep_counts:
        if 2 * n > len(x):
            continue
        key = f"N={n}"
        grid[key] = {}
        mde[key] = None
        for eff in effect_sizes_pct:
            flags = _resample_flag_count(rng, x, n, trials_per_point, alpha, scale=1 + eff / 100.0)
            pw = flags / trials_per_point
            grid[key][f"+{eff:g}%"] = round(pw, 3)
            if pw >= 0.8 and mde[key] is None:
                mde[key] = eff

    return {
        "trials_per_point": trials_per_point,
        "alpha": alpha,
        "pool_size": len(x),
        "power_grid": grid,
        "mde_at_80_pct_power": mde,
    }
