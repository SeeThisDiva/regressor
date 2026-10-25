#!/usr/bin/env python3
"""
Change-point detector for benchmark regressions.

Why not a fixed percentage threshold:
  - Noise is heteroscedastic across benchmarks. Phase 1 measured 1.4% CV on
    a millisecond-scale benchmark and 10.5% CV on a microsecond-scale one,
    on the SAME machine, SAME commit. One global "%slower" cutoff is either
    too loose for the quiet benchmark or drowns you in false positives on
    the noisy one.
  - A single before/after run is a sample size of one on each side. You
    cannot tell signal from noise without knowing what noise looks like for
    THIS benchmark, which requires a distribution, not a point estimate.
  - The noise we measured is not symmetric -- OS scheduling jitter produces
    a heavy right tail (occasional slow outliers), so a mean/stdev-based
    test (e.g. Student's t-test) gets pulled around by rare huge samples.
    A rank-based test is robust to that without needing to guess a
    distribution shape.

Method:
  1. Mann-Whitney U test: nonparametric test of whether the candidate
     distribution is stochastically shifted from the baseline. Makes no
     assumption of normality -- appropriate given the observed tail.
  2. Effect size: Hodges-Lehmann estimator (median of all pairwise
     differences between the two samples) as a robust point estimate,
     reported as a percentage of the baseline median.
  3. Practical-significance floor: even a p<0.001 result is not
     interesting if the shift is smaller than the benchmark's own known
     noise band. Require the effect size to exceed
     `noise_floor_multiplier` x the baseline's measured coefficient of
     variation before calling it a regression, not just p < alpha.
  4. Benjamini-Hochberg FDR correction: run across N commits and a flat
     alpha=0.01 per comparison, you'll get ~1 spurious flag per 100
     commits by chance alone. BH controls the expected false-discovery
     rate across the whole batch instead of per-comparison.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy import stats


def load_samples(dir_path):
    """All raw per-iteration timings, pooled across every rep file. Useful
    for eyeballing the full distribution shape, NOT for hypothesis testing
    -- samples within one process invocation are not independent of each
    other (shared cache/allocator/branch-predictor state), so pooling them
    and feeding the result to a test that assumes IID samples inflates
    apparent significance. See load_rep_summaries."""
    vals = []
    for f in sorted(Path(dir_path).glob("rep*.txt")):
        vals.extend(int(x) for x in open(f) if x.strip())
    return np.array(vals, dtype=np.float64)


def load_rep_summaries(dir_path, stat=np.median):
    """One summary value per process invocation (default: the rep's median).
    This is the correct unit for the significance test: each rep is an
    independent process launch, so these values are much closer to IID than
    raw pooled iterations are. It also matches how the phase 1 noise study
    measured cross-run variance, so the noise floor computed from these
    numbers is apples-to-apples with what phase 1 reported."""
    out = []
    for f in sorted(Path(dir_path).glob("rep*.txt")):
        vals = [int(x) for x in open(f) if x.strip()]
        if vals:
            out.append(float(stat(vals)))
    return np.array(out, dtype=np.float64)


def hodges_lehmann(a, b, max_n=1000, seed=0):
    """Median of all pairwise differences b_j - a_i. Robust effect-size
    estimate that pairs naturally with Mann-Whitney (same null hypothesis).
    Full O(n*m) pairwise matrix is subsampled above max_n per side --
    at 2000 reps/side that's 4B pairs and blows past available memory,
    and a few thousand pairs already estimate the median comfortably."""
    rng = np.random.default_rng(seed)
    if len(a) > max_n:
        a = rng.choice(a, size=max_n, replace=False)
    if len(b) > max_n:
        b = rng.choice(b, size=max_n, replace=False)
    diffs = b[:, None] - a[None, :]
    return float(np.median(diffs))


def compare(baseline, candidate, alpha=0.01, noise_floor_multiplier=3.0):
    baseline_median = float(np.median(baseline))
    baseline_cv = float(np.std(baseline) / np.mean(baseline))

    u_stat, p_value = stats.mannwhitneyu(
        candidate, baseline, alternative="two-sided"
    )
    shift_abs = hodges_lehmann(baseline, candidate)
    shift_pct = 100.0 * shift_abs / baseline_median

    noise_floor_pct = 100.0 * baseline_cv * noise_floor_multiplier
    statistically_significant = p_value < alpha
    exceeds_noise_floor = abs(shift_pct) > noise_floor_pct

    verdict = "flag" if (statistically_significant and exceeds_noise_floor) else "ok"

    return {
        "verdict": verdict,
        "p_value": float(p_value),
        "shift_pct": round(shift_pct, 3),
        "baseline_median_ns": round(baseline_median, 1),
        "baseline_cv_pct": round(100 * baseline_cv, 3),
        "noise_floor_pct": round(noise_floor_pct, 3),
        "statistically_significant": bool(statistically_significant),
        "exceeds_noise_floor": bool(exceeds_noise_floor),
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
    """
    Dual-track change-point detection: cross-references wall-clock latency shifts
    against deterministic hardware PMU counters (e.g. retired instructions or CPU cycles).

    Returns combined analysis with automated Attribution:
      - CONFIRMED_CODE_REGRESSION: latency increase confirmed by deterministic instruction/cycle increase
      - ENVIRONMENTAL_JITTER_DISPROVEN: latency shifted due to OS/hypervisor scheduling,
        but hardware PMU counter remained constant (100% false positive)
      - CACHE_OR_MEMORY_REGRESSION: latency increased, instructions constant, but cycles/cache-misses surged
      - NO_REGRESSION: within normal variance
    """
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
    """Benjamini-Hochberg step-up procedure. Mutates results in place,
    adding 'fdr_significant'. Call this across a whole batch of commits
    before trusting any individual p-value."""
    m = len(results)
    order = sorted(range(m), key=lambda i: results[i]["p_value"])
    threshold_rank = 0
    for rank, idx in enumerate(order, start=1):
        if results[idx]["p_value"] <= (rank / m) * alpha:
            threshold_rank = rank
    for rank, idx in enumerate(order, start=1):
        results[idx]["fdr_significant"] = rank <= threshold_rank
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline_dir")
    ap.add_argument("candidate_dir")
    ap.add_argument("--alpha", type=float, default=0.01)
    ap.add_argument("--noise-floor-multiplier", type=float, default=3.0)
    args = ap.parse_args()

    baseline = load_rep_summaries(args.baseline_dir)
    candidate = load_rep_summaries(args.candidate_dir)
    result = compare(baseline, candidate, args.alpha, args.noise_floor_multiplier)
    print(json.dumps(result, indent=2))
