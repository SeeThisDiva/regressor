#!/usr/bin/env python3
import json
from pathlib import Path
import sys
import os

sys.path.insert(0, str(Path(__file__).parent))
from changepoint import compare, bh_fdr_correct  # noqa: E402
import numpy as np  # noqa: E402

BASE_DIR = Path(os.environ.get("NOISE_BENCH_DIR", Path(__file__).resolve().parent.parent))
RESULTS = BASE_DIR / "results" / "commits"
COMMITS_FILE = BASE_DIR / "harness" / "commits.txt"
COMMITS = [
    l.strip()
    for l in open(COMMITS_FILE, encoding="utf-8")
    if l.strip()
]
BENCHES = ["compile_moderate", "find_iter_userid", "is_match_status"]


def load_bench_rep_medians(short_sha_dir, bench):
    out = []
    for f in sorted(short_sha_dir.glob(f"{bench}_rep*.txt")):
        vals = [int(x) for x in open(f) if x.strip()]
        if vals:
            out.append(float(np.median(vals)))
    return np.array(out, dtype=np.float64)


def find_dir(short8):
    matches = [d for d in RESULTS.iterdir() if d.name.startswith(short8)]
    return matches[0] if matches else None


def meta_for(d):
    p = d / "meta.json"
    return json.loads(p.read_text()) if p.exists() else {}


def main():
    results = []
    for i in range(1, len(COMMITS)):
        base_sha, cand_sha = COMMITS[i - 1], COMMITS[i]
        base_dir, cand_dir = find_dir(base_sha), find_dir(cand_sha)
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
            baseline = load_bench_rep_medians(base_dir, bench)
            candidate = load_bench_rep_medians(cand_dir, bench)
            if len(baseline) < 5 or len(candidate) < 5:
                continue
            r = compare(baseline, candidate)
            r.update(
                {
                    "bench": bench,
                    "base_sha": base_sha,
                    "cand_sha": cand_sha,
                    "cand_subject": cand_meta.get("commit_subject", ""),
                    "host_changed": host_changed,
                }
            )
            results.append(r)

    bh_fdr_correct(results, alpha=0.05)

    n_flagged_raw = sum(1 for r in results if r["verdict"] == "flag")
    n_flagged_fdr = sum(
        1 for r in results if r["verdict"] == "flag" and r["fdr_significant"]
    )

    print(f"Total comparisons: {len(results)}  "
          f"({len(COMMITS)-1} adjacent commit pairs x {len(BENCHES)} benchmarks)")
    print(f"Flagged (p<alpha AND exceeds noise floor), pre-FDR: {n_flagged_raw}")
    print(f"Flagged after BH-FDR correction: {n_flagged_fdr}")
    print()

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

    output_file = BASE_DIR / "results" / "batch_analysis.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
