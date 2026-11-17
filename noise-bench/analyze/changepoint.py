#!/usr/bin/env python3
"""
Change-point detector for benchmark regressions (standalone noise-bench module).

Why not a fixed percentage threshold:
  - Noise is heteroscedastic across benchmarks. Baseline calibration measured
    1.4% CV on a millisecond-scale benchmark and 10.5% CV on a microsecond-scale
    one on the SAME machine and commit. One global "% slower" cutoff is either
    too loose for the quiet benchmark or floods you with false positives on the
    noisy one.
  - A single before/after run has sample size 1 on each side; telling signal
    from noise requires a distribution of independent process invocations.
  - Measured OS scheduling jitter has a heavy right tail, which pulls mean/stdev
    tests (e.g. Student's t-test) around. Rank-based tests stay robust without
    assuming normality.

Method:
  1. Mann-Whitney U test across per-process summary medians.
  2. Hodges-Lehmann effect size (median of pairwise differences), reported as
     a percentage of the baseline median.
  3. Practical-significance floor: shift must exceed
     `noise_floor_multiplier` x baseline CV (note: this standalone module keeps
     population std `ddof=0` for parity with Study 1's `batch_analysis.json`,
     while `core/detector.py` uses sample std `ddof=1`).
  4. Benjamini-Hochberg FDR correction across the batch of comparisons.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from scipy import stats


def _read_int_samples(path):
    """Read non-empty integer timing lines from a single sample file."""
    with Path(path).open(encoding="utf-8") as fh:
        return [int(line) for line in fh if line.strip()]


def load_samples(dir_path, pattern="rep*.txt"):
    """Load all raw per-iteration timings pooled across matching files.

    Useful for inspecting distribution shape, NOT for hypothesis testing:
    iterations within one process invocation share cache, allocator, and
    branch-predictor state, so pooling them violates independence and inflates
    apparent significance. Use load_rep_summaries() for testing.
    """
    vals = []
    for path in sorted(Path(dir_path).glob(pattern)):
        vals.extend(_read_int_samples(path))
    return np.array(vals, dtype=np.float64)


def load_rep_summaries(dir_path, stat=np.median, pattern="rep*.txt"):
    """Load one summary statistic (default: median) per independent process run.

    Each file represents a separate process launch, making these summaries far
    closer to i.i.d. draws than pooled inner iterations.
    """
    out = []
    for path in sorted(Path(dir_path).glob(pattern)):
        vals = _read_int_samples(path)
        if vals:
            out.append(float(stat(vals)))
    return np.array(out, dtype=np.float64)


def hodges_lehmann(a, b, max_n=1000, seed=0):
    """Median of all pairwise differences b_j - a_i.

    Subsamples to `max_n` per side to bound memory/runtime on large vectors.
    """
    rng = np.random.default_rng(seed)
    if len(a) > max_n:
        a = rng.choice(a, size=max_n, replace=False)
    if len(b) > max_n:
        b = rng.choice(b, size=max_n, replace=False)
    diffs = b[:, None] - a[None, :]
    return float(np.median(diffs))


def compare(baseline, candidate, alpha=0.01, noise_floor_multiplier=3.0):
    """Compare two independent arrays of per-run medians for a shift."""
    baseline = np.asarray(baseline, dtype=np.float64)
    candidate = np.asarray(candidate, dtype=np.float64)
    if len(baseline) == 0 or len(candidate) == 0:
        raise ValueError("baseline and candidate must both be non-empty")

    baseline_median = float(np.median(baseline))
    baseline_mean = float(np.mean(baseline))
    baseline_cv = float(np.std(baseline) / baseline_mean) if baseline_mean > 0 else 0.0

    _, p_value = stats.mannwhitneyu(candidate, baseline, alternative="two-sided")
    shift_abs = hodges_lehmann(baseline, candidate)
    shift_pct = (100.0 * shift_abs / baseline_median) if baseline_median > 0 else 0.0

    noise_floor_pct = 100.0 * baseline_cv * noise_floor_multiplier
    statistically_significant = bool(p_value < alpha)
    exceeds_noise_floor = bool(abs(shift_pct) > noise_floor_pct)
    verdict = "flag" if (statistically_significant and exceeds_noise_floor) else "ok"

    return {
        "verdict": verdict,
        "p_value": float(p_value),
        "shift_pct": round(shift_pct, 3),
        "baseline_median_ns": round(baseline_median, 1),
        "baseline_cv_pct": round(100 * baseline_cv, 3),
        "noise_floor_pct": round(noise_floor_pct, 3),
        "statistically_significant": statistically_significant,
        "exceeds_noise_floor": exceeds_noise_floor,
        "n_baseline": len(baseline),
        "n_candidate": len(candidate),
    }


def compare_dual(
    time_base,
    time_cand,
    pmu_base=None,
    pmu_cand=None,
    alpha=0.01,
    noise_floor_multiplier=3.0,
    pmu_metric_name="instructions",
):
    """Cross-reference wall-clock latency shifts against PMU cycle/instruction counts."""
    time_res = compare(time_base, time_cand, alpha=alpha, noise_floor_multiplier=noise_floor_multiplier)

    if pmu_base is not None and pmu_cand is not None and len(pmu_base) >= 5 and len(pmu_cand) >= 5:
        pmu_res = compare(pmu_base, pmu_cand, alpha=alpha, noise_floor_multiplier=noise_floor_multiplier)
        time_flagged = time_res["verdict"] == "flag"
        pmu_flagged = pmu_res["verdict"] == "flag"
        pmu_shift = pmu_res["shift_pct"]

        if time_flagged and pmu_flagged and pmu_shift > 0:
            attribution = "CONFIRMED_CODE_REGRESSION"
            confidence = "HIGH (99%)"
            recommendation = (
                f"Real algorithmic regression detected. {pmu_metric_name.title()} "
                f"increased by {pmu_shift:+.2f}% along with latency."
            )
        elif time_flagged and abs(pmu_shift) <= 0.2:
            attribution = "ENVIRONMENTAL_JITTER_DISPROVEN"
            confidence = "HIGH (False Positive)"
            recommendation = (
                f"Spurious flag caused by host/hypervisor scheduling noise. Deterministic "
                f"{pmu_metric_name} changed by only {pmu_shift:+.2f}%. Do not block CI."
            )
        elif time_flagged and pmu_shift > 0 and not pmu_flagged:
            attribution = "BORDERLINE_REGRESSION"
            confidence = "MODERATE"
            recommendation = (
                f"Latency shift flagged, but {pmu_metric_name} shift ({pmu_shift:+.2f}%) "
                f"did not exceed the PMU noise floor."
            )
        elif time_flagged and pmu_shift < 0:
            attribution = "ANOMALOUS_DIVERGENCE"
            confidence = "INVESTIGATE"
            recommendation = "Latency increased while PMU counters decreased. Possible lock contention or I/O wait."
        else:
            attribution = "NO_REGRESSION"
            confidence = "HIGH"
            recommendation = "Metrics within acceptable noise threshold."

        result = dict(time_res)
        result["pmu_analysis"] = {
            "metric": pmu_metric_name,
            "verdict": pmu_res["verdict"],
            "shift_pct": pmu_res["shift_pct"],
            "p_value": pmu_res["p_value"],
            "baseline_median": pmu_res["baseline_median_ns"],
            "noise_floor_pct": pmu_res["noise_floor_pct"],
        }
        result["attribution"] = attribution
        result["attribution_confidence"] = confidence
        result["recommendation"] = recommendation
        return result

    time_res["attribution"] = "FLAGGED_LATENCY_ONLY" if time_res["verdict"] == "flag" else "NO_REGRESSION"
    time_res["attribution_confidence"] = "UNVERIFIED (Requires PMU)"
    time_res["recommendation"] = "Wall-clock shift only. Re-run with --pmu or differential flamegraphs to confirm."
    return time_res


def bh_fdr_correct(results, alpha=0.05):
    """Apply Benjamini-Hochberg step-up FDR correction in place ('fdr_significant')."""
    m = len(results)
    if m == 0:
        return results
    order = sorted(range(m), key=lambda i: results[i]["p_value"])
    threshold_rank = 0
    for rank, idx in enumerate(order, start=1):
        if results[idx]["p_value"] <= (rank / m) * alpha:
            threshold_rank = rank
    for rank, idx in enumerate(order, start=1):
        results[idx]["fdr_significant"] = rank <= threshold_rank
    return results


def main():
    ap = argparse.ArgumentParser(
        description="Compare baseline vs candidate per-run benchmark directories (Mann-Whitney U + 3x CV floor)."
    )
    ap.add_argument("baseline_dir", help="Directory containing baseline rep*.txt files")
    ap.add_argument("candidate_dir", help="Directory containing candidate rep*.txt files")
    ap.add_argument("--alpha", type=float, default=0.01, help="Mann-Whitney significance threshold (default: 0.01)")
    ap.add_argument(
        "--noise-floor-multiplier",
        type=float,
        default=3.0,
        help="Minimum |shift| / baseline CV ratio required to flag (default: 3.0)",
    )
    args = ap.parse_args()

    baseline = load_rep_summaries(args.baseline_dir)
    candidate = load_rep_summaries(args.candidate_dir)
    result = compare(baseline, candidate, args.alpha, args.noise_floor_multiplier)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
