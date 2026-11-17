#!/usr/bin/env python3
"""Summarize cross-run CV and within-run p99/p50 tail ratio for a baseline noise study."""

import argparse
import os
import statistics
import sys
from pathlib import Path

BASE_DIR = Path(os.environ.get("NOISE_BENCH_DIR", Path(__file__).resolve().parent))
BENCHES = ["compile_moderate", "find_iter_userid", "is_match_status"]


def _latest_baseline_dir():
    candidates = sorted((BASE_DIR / "results").glob("*_baseline"))
    if not candidates:
        raise FileNotFoundError(f"no *_baseline directory found under {BASE_DIR / 'results'}")
    return candidates[-1]


def summarize_benchmark(outdir, bench):
    """Return summary metrics dict for `bench` inside `outdir`."""
    files = sorted(outdir.glob(f"{bench}_rep*.txt"))
    if not files:
        raise FileNotFoundError(f"no {bench}_rep*.txt files found in {outdir}")

    run_medians = []
    tail_ratios = []
    for path in files:
        with path.open(encoding="utf-8") as fh:
            vals = sorted(int(line) for line in fh if line.strip())
        if not vals:
            continue
        n = len(vals)
        med = vals[n // 2]
        p99 = vals[int(n * 0.99)]
        run_medians.append(med)
        tail_ratios.append(p99 / med if med > 0 else 0.0)

    if not run_medians:
        raise ValueError(f"all sample files for {bench} in {outdir} were empty")

    mean_val = statistics.mean(run_medians)
    stdev_val = statistics.stdev(run_medians) if len(run_medians) > 1 else 0.0
    cv_pct = (100.0 * stdev_val / mean_val) if mean_val > 0 else 0.0
    lo, hi = min(run_medians), max(run_medians)

    return {
        "reps": len(run_medians),
        "iters": len(vals),
        "mean": mean_val,
        "stdev": stdev_val,
        "cv_pct": cv_pct,
        "min": lo,
        "max": hi,
        "max_over_min": (hi / lo) if lo > 0 else 0.0,
        "tail_mean": statistics.mean(tail_ratios),
        "tail_worst": max(tail_ratios),
    }


def main():
    ap = argparse.ArgumentParser(description="Analyze cross-run baseline noise from run_noise_study.sh output.")
    ap.add_argument(
        "outdir",
        nargs="?",
        type=Path,
        default=None,
        help="Baseline results directory (default: latest results/*_baseline under noise-bench)",
    )
    args = ap.parse_args()

    try:
        outdir = args.outdir if args.outdir is not None else _latest_baseline_dir()
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Analyzing: {outdir}\n")
    for bench in BENCHES:
        stats = summarize_benchmark(outdir, bench)
        print(f"=== {bench} ===")
        print(f"  across {stats['reps']} runs, each run's median of {stats['iters']} iters (ns):")
        print(f"    mean={stats['mean']:,.0f}  stdev={stats['stdev']:,.0f}  CV={stats['cv_pct']:.2f}%")
        print(f"    min={stats['min']:,}  max={stats['max']:,}  max/min={stats['max_over_min']:.2f}x")
        print("  within a single run, p99/p50 ratio (tail heaviness):")
        print(f"    mean={stats['tail_mean']:.2f}x  worst={stats['tail_worst']:.2f}x\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
