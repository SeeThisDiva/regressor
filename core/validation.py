"""
core/validation.py
Mandatory synthetic validation harness for adapters and canary benchmarks.
Before trusting any adapter on real history, it must pass a 3-point synthetic injection test:
  1. True Negative: Same code vs itself -> Must NOT be flagged (verdict "ok": not significant at
     alpha=0.01, or within the noise floor).
  2. Large Injection (~8% of baseline median) -> MUST be flagged (p < 0.01, shift > noise_floor).
  3. Small Injection (~1% of baseline median) -> Gated out by the noise floor, OR legitimately
     detected when the measured floor is below the injected size. On a quiet host (floor < 1%)
     flagging a real 1% slowdown is the CORRECT outcome; requiring "not flagged" there would
     make the gate fail precisely when the machine is good. This is a sanity check (it catches
     adapters that ignore or wildly amplify inject_ns), not a sensitivity test.

Note: the four sets are collected one after another, not interleaved, so slow host drift
during validation can affect the gates. Re-run on a failure before blaming the adapter.
"""

import sys
from pathlib import Path

import numpy as np

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from adapters.base import BaseAdapter
from core.canary import CanaryBenchmark
from core.detector import compare_distributions
from core.models import SyntheticValidationResult


def validate_adapter_synthetic(
    adapter: BaseAdapter,
    bench_name: str,
    reps: int = 25,
    iters: int = 1000,
    warmup: int = 100
) -> SyntheticValidationResult:
    """
    Executes the 3-point synthetic injection test on an adapter.
    Uses real busy-wait CPU cycles to generate true timing signals.
    """
    print(f"\n[Synthetic Validation] Testing adapter '{adapter.__class__.__name__}' on benchmark '{bench_name}'...")

    # Discard 3 full warmup reps to prime OS process/AV caches, CPU frequency governor, and i-cache
    try:
        for _ in range(3):
            adapter.run(bench_name, iters, warmup, inject_ns=0)
    except Exception:
        pass

    # Step 1: Baseline A
    print("  Collecting baseline A (0ns injection)...")
    base_a_medians = [float(np.median(adapter.run(bench_name, iters, warmup, inject_ns=0))) for _ in range(reps)]
    base_median_ns = float(np.median(base_a_medians))
    print(f"  Baseline median: {base_median_ns:,.1f} ns")

    # Step 2: Baseline B (True Negative: Same code vs itself)
    print("  Collecting baseline B (0ns injection, true negative check)...")
    base_b_medians = [float(np.median(adapter.run(bench_name, iters, warmup, inject_ns=0))) for _ in range(reps)]
    tn_res = compare_distributions(np.array(base_a_medians), np.array(base_b_medians))
    tn_ok = (tn_res["verdict"] == "ok")
    print(f"  -> True Negative: shift={tn_res['shift_pct']:+.2f}%, p={tn_res['p_value']:.3e} [Verdict: {tn_res['verdict'].upper()}] (Passed: {tn_ok})")

    # Step 3: Large ~8% Injected Slowdown
    large_inject_ns = max(int(base_median_ns * 0.08), 200)
    print(f"  Collecting large injection (+{large_inject_ns:,} ns, ~8% target)...")
    large_inj_medians = [float(np.median(adapter.run(bench_name, iters, warmup, inject_ns=large_inject_ns))) for _ in range(reps)]
    large_res = compare_distributions(np.array(base_a_medians), np.array(large_inj_medians))
    large_flagged = (large_res["verdict"] == "flag")
    print(f"  -> Large Injection: shift={large_res['shift_pct']:+.2f}%, p={large_res['p_value']:.3e} [Verdict: {large_res['verdict'].upper()}] (Passed: {large_flagged})")

    # Step 4: Small ~1% Injected Slowdown (Sensitivity Floor / Noise Gate Check)
    small_inject_ns = max(int(base_median_ns * 0.01), 25)
    print(f"  Collecting small injection (+{small_inject_ns:,} ns, ~1% target)...")
    small_inj_medians = [float(np.median(adapter.run(bench_name, iters, warmup, inject_ns=small_inject_ns))) for _ in range(reps)]
    small_res = compare_distributions(np.array(base_a_medians), np.array(small_inj_medians))
    small_target_pct = 100.0 * small_inject_ns / base_median_ns
    small_detectable = bool(
        small_res["noise_floor_pct"] < small_target_pct
        and abs(small_res["shift_pct"]) <= 3.0 * small_target_pct
    )
    # Either gated by the floor, or the floor is below the injected size (without wild amplification).
    small_gated = (small_res["verdict"] == "ok") or small_detectable
    print(f"  -> Small Injection: shift={small_res['shift_pct']:+.2f}%, floor={small_res['noise_floor_pct']:.2f}% [Verdict: {small_res['verdict'].upper()}] (Passed: {small_gated}; injected {small_target_pct:.2f}%, floor {'below' if small_detectable else 'above'} it)")

    all_passed = bool(tn_ok and large_flagged and small_gated)
    status_str = "PASSED ALL 3 GATES" if all_passed else "FAILED VALIDATION"
    print(f"  Result: {status_str}\n")

    return SyntheticValidationResult(
        adapter_name=adapter.__class__.__name__,
        benchmark=bench_name,
        true_negative_ok=tn_ok,
        true_negative_p_value=tn_res["p_value"],
        large_injection_flagged=large_flagged,
        large_injection_p_value=large_res["p_value"],
        large_injection_shift_pct=large_res["shift_pct"],
        small_injection_gated=small_gated,
        small_injection_p_value=small_res["p_value"],
        small_injection_shift_pct=small_res["shift_pct"],
        noise_floor_pct=tn_res["noise_floor_pct"],
        all_passed=all_passed,
    )


def validate_canary_synthetic(reps: int = 15) -> bool:
    """
    Validates that the Canary drift detector correctly detects real injected SHA-256 work.
    """
    print("[Canary Validation] Testing canary host-drift detector (P4 #18)...")
    # Warm up the Python SHA-256 loop after subprocess benchmark activity settles
    for _ in range(4):
        CanaryBenchmark.run_sample()
    base_samples = []
    normal_cand = []
    drifted_cand = []
    for _ in range(reps):
        base_samples.append(CanaryBenchmark.run_sample())
        normal_cand.append(CanaryBenchmark.run_sample())
        drifted_cand.append(CanaryBenchmark.run_sample(inject_jitter_pct=25.0))

    res_normal = CanaryBenchmark.evaluate_drift(base_samples, normal_cand)
    res_drifted = CanaryBenchmark.evaluate_drift(base_samples, drifted_cand)

    normal_ok = (res_normal["status"] == "OK")
    drift_caught = (res_drifted["status"] == "ENVIRONMENT_SUSPECT")

    print(f"  -> Normal canary: shift={res_normal['shift_pct']:+.2f}% [Status: {res_normal['status']}] (Passed: {normal_ok})")
    print(f"  -> Injected +25% extra SHA-256 work: shift={res_drifted['shift_pct']:+.2f}% [Status: {res_drifted['status']}] (Passed: {drift_caught})")

    passed = normal_ok and drift_caught
    print(f"  Canary Validation: {'PASSED' if passed else 'FAILED'}\n")
    return passed
