#!/usr/bin/env python3
"""Build `base` and `cand` standalone repro binaries and run randomized interleaved A/B pairs."""

from __future__ import annotations

import argparse
import math
import platform
import random
import statistics
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent


def build_variant(label: str) -> Path:
    manifest = ROOT / label / "Cargo.toml"
    target_dir = ROOT / "target" / label
    cmd = ["cargo", "build", "--release", "--manifest-path", str(manifest), "--target-dir", str(target_dir)]
    print(f"[build] {label}: {' '.join(cmd)}", flush=True)
    res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=900)
    if res.returncode != 0:
        raise RuntimeError(f"Build failed for {label}:\n{res.stderr}")
    exe = "repro.exe" if platform.system() == "Windows" else "repro"
    bin_path = target_dir / "release" / exe
    if not bin_path.exists():
        raise FileNotFoundError(f"Expected binary not found: {bin_path}")
    return bin_path


def run_once(bin_path: Path, iters: int, warmup: int) -> float:
    out = subprocess.check_output([str(bin_path), str(iters), str(warmup)], text=True, timeout=120)
    vals = [int(line) for line in out.splitlines() if line.strip()]
    if len(vals) != iters:
        raise RuntimeError(f"Expected {iters} samples from {bin_path.name}, got {len(vals)}")
    return float(statistics.median(vals))


def walsh_hl(diffs: List[float]) -> float:
    avgs = [
        0.5 * (diffs[i] + diffs[j])
        for i in range(len(diffs))
        for j in range(i, len(diffs))
    ]
    return float(statistics.median(avgs))


def bootstrap_ci(diffs: List[float], n_boot: int = 2000, seed: int = 0) -> Tuple[float, float]:
    rng = random.Random(seed)
    n = len(diffs)
    ests = sorted(walsh_hl([diffs[rng.randrange(n)] for _ in range(n)]) for _ in range(n_boot))
    return ests[int(0.025 * n_boot)], ests[min(n_boot - 1, int(0.975 * n_boot))]


def wilcoxon_p(diffs: List[float]) -> float:
    try:
        from scipy import stats  # type: ignore

        nonzero = [d for d in diffs if d != 0]
        if not nonzero:
            return 1.0
        return float(stats.wilcoxon(diffs, alternative="two-sided", zero_method="wilcox").pvalue)
    except ImportError:
        # Pure-stdlib exact sign-rank fallback for small N (or normal approx if ties/large N).
        nz = [d for d in diffs if d != 0]
        n = len(nz)
        if n == 0:
            return 1.0
        ranked = sorted(enumerate(nz), key=lambda kv: abs(kv[1]))
        w_plus = 0.0
        i = 0
        while i < n:
            j = i
            while j + 1 < n and abs(ranked[j + 1][1]) == abs(ranked[i][1]):
                j += 1
            avg_rank = 0.5 * ((i + 1) + (j + 1))
            for k in range(i, j + 1):
                if ranked[k][1] > 0:
                    w_plus += avg_rank
            i = j + 1
        mean_w = n * (n + 1) / 4.0
        std_w = math.sqrt(n * (n + 1) * (2 * n + 1) / 24.0)
        z = (w_plus - mean_w) / std_w if std_w > 0 else 0.0
        return math.erfc(abs(z) / math.sqrt(2.0))


def main() -> int:
    ap = argparse.ArgumentParser(description="Run randomized interleaved A/B reproducer.")
    ap.add_argument("--pairs", type=int, default=30, help="Interleaved A/B process pairs (default: 30)")
    ap.add_argument("--iters", type=int, default=2000, help="Timed iterations per process (default: 2000)")
    ap.add_argument("--warmup", type=int, default=200, help="Warmup iterations per process (default: 200)")
    ap.add_argument("--seed", type=int, default=0, help="RNG seed for AB/BA pair order")
    args = ap.parse_args()

    base_bin = build_variant("base")
    cand_bin = build_variant("cand")

    rng = random.Random(args.seed)
    base_meds: List[float] = []
    cand_meds: List[float] = []

    print(f"[run] running {args.pairs} randomized interleaved pairs ...", flush=True)
    for _ in range(args.pairs):
        if rng.random() < 0.5:
            base_meds.append(run_once(base_bin, args.iters, args.warmup))
            cand_meds.append(run_once(cand_bin, args.iters, args.warmup))
        else:
            cand_meds.append(run_once(cand_bin, args.iters, args.warmup))
            base_meds.append(run_once(base_bin, args.iters, args.warmup))

    diffs = [100.0 * (c - b) / b for b, c in zip(base_meds, cand_meds)]
    hl = walsh_hl(diffs)
    ci_lo, ci_hi = bootstrap_ci(diffs)
    p_val = wilcoxon_p(diffs)

    print("\n=== Interleaved Repro Summary ===")
    print(f"Base median:      {statistics.median(base_meds):,.1f} ns")
    print(f"Candidate median: {statistics.median(cand_meds):,.1f} ns")
    print(f"Shift (HL):       {hl:+.2f}%  (95% CI [{ci_lo:+.2f}%, {ci_hi:+.2f}%])")
    print(f"Wilcoxon p:       {p_val:.2e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
