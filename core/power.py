"""
core/power.py
False-positive rate and power, measured three ways so the number means something.

1. Within-session A/A, random split   — same commit, same session, runs shuffled.
   Measures the detector's FPR when the only noise is run-to-run jitter.
2. Within-session A/A, contiguous split — first half of the session vs second half.
   Adds slow drift *within* a session (minutes).
3. Real null transitions               — adjacent commits in the history whose
   candidate is documentation-only (classified by commit subject "doc:"/"docs:").
   Same compiled code, measured in separate runs; this is the condition that
   produced the real false positives, including drift *between* sessions.

(1) is what most A/A tests report and it is close to meaningless here: every
real false positive came from (3). Reporting all three, with exact binomial
confidence intervals, shows the gap.

Power is simulated by scaling a resample of real within-session runs. It
therefore describes power under within-session noise only.
"""

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
from scipy import stats

from core.detector import compare_distributions
from core.samples import parse_samples

NULL_SUBJECT = re.compile(r"^(doc|docs)(\(.*\))?:", re.IGNORECASE)


def binom_ci(k: int, n: int, level: float = 0.95) -> List[float]:
    """Exact (Clopper-Pearson) confidence interval for a proportion, in percent."""
    if n == 0:
        return [0.0, 100.0]
    ci = stats.binomtest(k, n).proportion_ci(confidence_level=level, method="exact")
    return [round(100 * ci.low, 2), round(100 * ci.high, 2)]


def load_session_medians(session_dir: Path, benches: Iterable[str]) -> Dict[str, List[float]]:
    """Per-run medians from a single-session study directory, in run order."""
    out: Dict[str, List[float]] = {}
    for b in benches:
        meds = []
        for f in sorted(Path(session_dir).glob(f"{b}_rep*.txt")):
            meds.append(float(np.median(parse_samples(f.read_text(), source=str(f)))))
        if meds:
            out[b] = meds
    return out


def aa_random_split(medians: List[float], trials: int = 1000, alpha: float = 0.01,
                    seed: int = 42) -> Dict[str, Any]:
    """Shuffle the session's runs and split them in half, `trials` times (no replacement)."""
    rng = np.random.default_rng(seed)
    x = np.asarray(medians, dtype=np.float64)
    h = len(x) // 2
    flags = 0
    for _ in range(trials):
        p = rng.permutation(x)
        if compare_distributions(p[:h], p[h:2 * h], alpha=alpha)["verdict"] == "flag":
            flags += 1
    return {"trials": trials, "flags": flags,
            "fpr_pct": round(100 * flags / trials, 2), "ci95_pct": binom_ci(flags, trials)}


def aa_contiguous_split(medians: List[float], alpha: float = 0.01) -> Dict[str, Any]:
    """First half of the session vs second half (captures within-session drift)."""
    x = np.asarray(medians, dtype=np.float64)
    h = len(x) // 2
    r = compare_distributions(x[:h], x[h:2 * h], alpha=alpha)
    return {"verdict": r["verdict"], "shift_pct": r["shift_pct"], "p_value": r["p_value"],
            "noise_floor_pct": r["noise_floor_pct"]}


def null_transition_fpr(comparisons: List[Dict[str, Any]], gap_threshold_min: float = 15.0) -> Dict[str, Any]:
    """FPR over real adjacent comparisons whose candidate commit is documentation-only.

    `comparisons` rows need: cand_subject, verdict, fdr_significant, session_gap_min,
    benchmark, cand_sha, shift_pct.
    """
    null = [c for c in comparisons if NULL_SUBJECT.match(c["cand_subject"] or "")]

    def summarize(rows):
        k = sum(1 for c in rows if c["verdict"] == "flag" and c["fdr_significant"])
        return {"n": len(rows), "flags": k,
                "fpr_pct": round(100 * k / len(rows), 2) if rows else 0.0,
                "ci95_pct": binom_ci(k, len(rows))}

    within = [c for c in null if c["session_gap_min"] is not None and c["session_gap_min"] <= gap_threshold_min]
    across = [c for c in null if c["session_gap_min"] is not None and c["session_gap_min"] > gap_threshold_min]
    return {
        "all": summarize(null),
        "within_session": summarize(within),
        "across_session_break": summarize(across),
        "null_commits": sorted({c["cand_sha"] for c in null}),
        "flagged": [{"cand_sha": c["cand_sha"], "benchmark": c["benchmark"], "shift_pct": round(c["shift_pct"], 2),
                     "session_gap_min": c["session_gap_min"]}
                    for c in null if c["verdict"] == "flag" and c["fdr_significant"]],
    }


def evaluate_power_curve(
    pool: List[float],
    effect_sizes_pct: Iterable[float] = (1.0, 2.0, 3.0, 5.0, 8.0, 10.0, 15.0),
    rep_counts: Iterable[int] = (5, 10, 15, 20, 25),
    trials_per_point: int = 300,
    alpha: float = 0.01,
    seed: int = 42,
) -> Dict[str, Any]:
    """P(flag | true slowdown = delta), drawing base and candidate WITHOUT replacement
    from one real session and scaling the candidate by (1 + delta)."""
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
            flags = 0
            for _ in range(trials_per_point):
                p = rng.permutation(x)
                base, cand = p[:n], p[n:2 * n] * (1 + eff / 100.0)
                if compare_distributions(base, cand, alpha=alpha)["verdict"] == "flag":
                    flags += 1
            pw = flags / trials_per_point
            grid[key][f"+{eff:g}%"] = round(pw, 3)
            if pw >= 0.8 and mde[key] is None:
                mde[key] = eff
    return {"trials_per_point": trials_per_point, "alpha": alpha, "pool_size": len(x),
            "power_grid": grid, "mde_at_80_pct_power": mde}
