#!/usr/bin/env python3
"""
Pinned 30-pair interleaved A/B confirmation runner for Study 3 triage.

Reuses `PinnedExecutionContext` and `detect_p_core_cpu` from `run_study3.py` so
follow-up verification uses the exact same P-core + `HIGH_PRIORITY_CLASS` pinning
as Study 3 while eliminating slow host drift via randomized AB/BA interleaving.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Sequence

ANALYZE_DIR = Path(__file__).resolve().parent
NOISE_BENCH_DIR = ANALYZE_DIR.parent
REPO_ROOT = NOISE_BENCH_DIR.parent
HARNESS_DIR = NOISE_BENCH_DIR / "harness"
for p in (str(REPO_ROOT), str(HARNESS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from adapters.regex_adapter import RegexAdapter  # noqa: E402
from core.canary import CanaryBenchmark  # noqa: E402
from core.detector import bh_fdr_correct  # noqa: E402
from core.interleaved import run_interleaved  # noqa: E402
from run_study3 import PinnedExecutionContext, detect_p_core_cpu  # noqa: E402


def _load_iters_overrides(path: Path) -> Dict[str, Dict[str, int]]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def run_pinned_interleaved(
    base_ref: str,
    cand_ref: str,
    benchmarks: Sequence[str],
    *,
    pairs: int = 30,
    iters: int = 1000,
    warmup: int = 100,
    canary_reps: int = 15,
    seed: int = 0,
    workdir: Path,
    iters_config: Path,
) -> Dict[str, Any]:
    """Build `base_ref` and `cand_ref`, then run pinned interleaved A/B pairs."""
    topo = detect_p_core_cpu()
    cpu_id = int(topo["cpu_id"])
    overrides = _load_iters_overrides(iters_config)
    adapter = RegexAdapter()

    with PinnedExecutionContext(cpu_id=cpu_id, high_priority=True) as pin_ctx:
        br_base = adapter.build(base_ref, workdir=workdir)
        if not br_base.ok or not br_base.artifact:
            raise RuntimeError(f"Base build failed for {base_ref}: {br_base.log_tail}")
        br_cand = adapter.build(cand_ref, workdir=workdir)
        if not br_cand.ok or not br_cand.artifact:
            raise RuntimeError(f"Cand build failed for {cand_ref}: {br_cand.log_tail}")

        canary_pre = CanaryBenchmark.run_reps(reps=canary_reps) if canary_reps > 0 else None
        results: List[Dict[str, Any]] = []
        for idx, bench in enumerate(benchmarks):
            ov = overrides.get(bench, {})
            b_iters = int(ov.get("iters", iters))
            b_warmup = int(ov.get("warmup", warmup))
            print(f"[interleaved] {bench} ({pairs} pairs, iters={b_iters}, warmup={b_warmup}) ...", flush=True)
            res = run_interleaved(
                adapter,
                bench,
                br_base.artifact,
                br_cand.artifact,
                pairs=pairs,
                iters=b_iters,
                warmup=b_warmup,
                alpha=0.01,
                min_effect_pct=1.0,
                seed=seed + idx,
            )
            res["artifact_a"] = Path(str(res.get("artifact_a", ""))).name
            res["artifact_b"] = Path(str(res.get("artifact_b", ""))).name
            results.append(res)

        canary = (
            CanaryBenchmark.evaluate_drift(canary_pre, CanaryBenchmark.run_reps(reps=canary_reps))
            if canary_pre is not None
            else None
        )

    bh_fdr_correct(results, alpha=0.01)
    for r in results:
        r["final_verdict"] = "flag" if (r["verdict"] == "flag" and r["fdr_significant"]) else "ok"
        r["canary_status"] = canary["status"] if canary else "NOT_RECORDED"

    return {
        "base_ref": base_ref,
        "cand_ref": cand_ref,
        "cpu_id": cpu_id,
        "priority": pin_ctx.priority_label,
        "base_artifact": str(Path(br_base.artifact).name),
        "cand_artifact": str(Path(br_cand.artifact).name),
        "base_build_seconds": br_base.seconds,
        "cand_build_seconds": br_cand.seconds,
        "canary": canary,
        "results": results,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Pinned 30-pair interleaved A/B confirmation runner.")
    ap.add_argument("--base", required=True, help="Baseline git ref")
    ap.add_argument("--cand", required=True, help="Candidate git ref")
    ap.add_argument("--bench", action="append", required=True, help="Benchmark name (repeatable)")
    ap.add_argument("--pairs", type=int, default=30, help="Interleaved A/B pairs (default: 30)")
    ap.add_argument("--iters", type=int, default=1000, help="Default iterations per rep (default: 1000)")
    ap.add_argument("--warmup", type=int, default=100, help="Default warmup iterations (default: 100)")
    ap.add_argument("--canary-reps", type=int, default=15, help="Canary reps before/after (default: 15)")
    ap.add_argument("--seed", type=int, default=0, help="RNG seed")
    ap.add_argument(
        "--workdir",
        type=Path,
        default=Path(tempfile.gettempdir()) / "regressor-triage-builds",
        help="Isolated build directory outside OneDrive",
    )
    ap.add_argument(
        "--iters-config",
        type=Path,
        default=HARNESS_DIR / "study3_iters.json",
        help="Per-benchmark iters/warmup override JSON",
    )
    ap.add_argument("--out", type=Path, required=True, help="Output JSON path")
    args = ap.parse_args()

    payload = run_pinned_interleaved(
        args.base,
        args.cand,
        args.bench,
        pairs=args.pairs,
        iters=args.iters,
        warmup=args.warmup,
        canary_reps=args.canary_reps,
        seed=args.seed,
        workdir=args.workdir,
        iters_config=args.iters_config,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    can = payload.get("canary")
    if can:
        print(f"[canary] {can['shift_pct']:+.2f}% -> {can['status']}")
    for r in payload["results"]:
        lo, hi = r["shift_ci95_pct"]
        print(
            f"  [{r['final_verdict']:4s}] {r['benchmark']:50s} "
            f"base={r['baseline_median_ns']:,.1f}ns cand={r['candidate_median_ns']:,.1f}ns "
            f"shift={r['shift_pct']:+.2f}% CI95=[{lo:+.2f}%, {hi:+.2f}%] p={r['p_value']:.2e}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
