#!/usr/bin/env python3
"""Run adjacent-commit pairwise change-point detection across a batch of commit directories."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from changepoint import bh_fdr_correct, compare, load_rep_summaries  # noqa: E402

BASE_DIR = Path(os.environ.get("NOISE_BENCH_DIR", Path(__file__).resolve().parent.parent))
DEFAULT_RESULTS_DIR = BASE_DIR / "results" / "commits"
DEFAULT_COMMITS_FILE = BASE_DIR / "harness" / "commits.txt"
DEFAULT_OUTPUT_FILE = BASE_DIR / "results" / "batch_analysis.json"
BENCHES = ["compile_moderate", "find_iter_userid", "is_match_status"]


def find_dir(results_dir, short_sha):
    """Return the first subdirectory under `results_dir` matching `short_sha`, or None."""
    if not results_dir.exists():
        return None
    matches = sorted(d for d in results_dir.iterdir() if d.is_dir() and d.name.startswith(short_sha))
    return matches[0] if matches else None


def meta_for(commit_dir):
    """Load `meta.json` for a commit result directory, or `{}` if absent."""
    meta_path = commit_dir / "meta.json"
    return json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}


def main():
    ap = argparse.ArgumentParser(description="Analyze adjacent commit pairs with Mann-Whitney U + 3x CV + BH-FDR.")
    ap.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR, help="Directory of per-commit run folders")
    ap.add_argument("--commits-file", type=Path, default=DEFAULT_COMMITS_FILE, help="Ordered list of commit SHAs")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_FILE, help="Output JSON summary path")
    ap.add_argument("--alpha", type=float, default=0.01, help="Per-pair Mann-Whitney alpha (default: 0.01)")
    ap.add_argument("--noise-floor-multiplier", type=float, default=3.0, help="Noise-floor multiplier (default: 3.0)")
    ap.add_argument("--fdr-alpha", type=float, default=0.05, help="Benjamini-Hochberg FDR level (default: 0.05)")
    args = ap.parse_args()

    if not args.commits_file.exists():
        print(f"Error: commits file not found: {args.commits_file}", file=sys.stderr)
        return 1

    commits = [line.strip() for line in args.commits_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    results = []

    for i in range(1, len(commits)):
        base_sha, cand_sha = commits[i - 1], commits[i]
        base_dir = find_dir(args.results_dir, base_sha)
        cand_dir = find_dir(args.results_dir, cand_sha)
        if base_dir is None or cand_dir is None:
            continue

        base_meta, cand_meta = meta_for(base_dir), meta_for(cand_dir)
        if not (base_meta.get("build", {}).get("ok") and cand_meta.get("build", {}).get("ok")):
            continue

        host_changed = (
            base_meta.get("environment", {}).get("cpu_model")
            != cand_meta.get("environment", {}).get("cpu_model")
        )
        for bench in BENCHES:
            pattern = f"{bench}_rep*.txt"
            baseline = load_rep_summaries(base_dir, pattern=pattern)
            candidate = load_rep_summaries(cand_dir, pattern=pattern)
            if len(baseline) < 5 or len(candidate) < 5:
                continue

            res = compare(
                baseline,
                candidate,
                alpha=args.alpha,
                noise_floor_multiplier=args.noise_floor_multiplier,
            )
            res.update(
                {
                    "bench": bench,
                    "base_sha": base_sha,
                    "cand_sha": cand_sha,
                    "cand_subject": cand_meta.get("commit_subject", ""),
                    "host_changed": host_changed,
                }
            )
            results.append(res)

    bh_fdr_correct(results, alpha=args.fdr_alpha)

    n_flagged_raw = sum(1 for r in results if r["verdict"] == "flag")
    n_flagged_fdr = sum(1 for r in results if r["verdict"] == "flag" and r["fdr_significant"])

    print(
        f"Total comparisons: {len(results)}  "
        f"({max(0, len(commits) - 1)} adjacent commit pairs x {len(BENCHES)} benchmarks)"
    )
    print(f"Flagged (p<alpha AND exceeds noise floor), pre-FDR: {n_flagged_raw}")
    print(f"Flagged after BH-FDR correction: {n_flagged_fdr}\n")

    for r in results:
        if r["verdict"] == "flag":
            fdr_tag = "FDR-OK" if r["fdr_significant"] else "FDR-DROPPED"
            host_tag = " [HOST CHANGED]" if r["host_changed"] else ""
            print(
                f"[{fdr_tag}]{host_tag} {r['bench']:20s} "
                f"{r['base_sha']}->{r['cand_sha']}  "
                f"shift={r['shift_pct']:+.2f}%  p={r['p_value']:.2e}  "
                f"noise_floor={r['noise_floor_pct']:.2f}%  "
                f"-- {r['cand_subject']}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
