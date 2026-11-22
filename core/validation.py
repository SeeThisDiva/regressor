"""
core/validation.py
Synthetic ground-truth validation harness for benchmark adapters and the host canary.

Before trusting any adapter on real history, it must pass a 3-point synthetic injection test:
  1. True Negative: Same code vs itself -> must NOT be flagged (verdict "ok").
  2. Large Injection (~8% of baseline median) -> MUST be flagged.
  3. Small Injection (~1% of baseline median) -> gated out by the noise floor, or
     legitimately detected when the measured floor is below the injected size without
     wild amplification.

Note: the four sample sets are collected sequentially rather than interleaved, so slow
host drift during validation can affect the gates.
"""

import numpy as np

from adapters.base import BaseAdapter
from core.canary import CanaryBenchmark
from core.detector import compare_distributions
from core.models import SyntheticValidationResult


def _collect_medians(
    adapter: BaseAdapter,
    bench_name: str,
    reps: int,
    iters: int,
    warmup: int,
    inject_ns: int = 0,
) -> np.ndarray:
    """Run ``reps`` benchmark repetitions and return an array of per-run medians."""
    return np.array(
        [float(np.median(adapter.run(bench_name, iters, warmup, inject_ns=inject_ns))) for _ in range(reps)],
        dtype=np.float64,
    )


def validate_adapter_synthetic(
    adapter: BaseAdapter,
    bench_name: str,
    reps: int = 25,
    iters: int = 1000,
    warmup: int = 100,
    min_noise_floor_pct: float = 0.0,
) -> SyntheticValidationResult:
    """Execute the 3-point synthetic injection validation test on an adapter."""
    print(f"\n[Synthetic Validation] Testing adapter '{adapter.__class__.__name__}' on benchmark '{bench_name}'...")

    # Discard 3 full warmup reps to prime OS caches, CPU frequency governor, and i-cache.
    try:
        for _ in range(3):
            adapter.run(bench_name, iters, warmup, inject_ns=0)
    except Exception:
        pass

    print("  Collecting baseline A (0ns injection)...")
    base_a = _collect_medians(adapter, bench_name, reps, iters, warmup)
    base_median_ns = float(np.median(base_a))
    print(f"  Baseline median: {base_median_ns:,.1f} ns")

    print("  Collecting baseline B (0ns injection, true negative check)...")
    base_b = _collect_medians(adapter, bench_name, reps, iters, warmup)
    tn_res = compare_distributions(base_a, base_b, min_noise_floor_pct=min_noise_floor_pct)
    tn_ok = tn_res["verdict"] == "ok"
    print(
        f"  -> True Negative: shift={tn_res['shift_pct']:+.2f}%, "
        f"p={tn_res['p_value']:.3e} [Verdict: {tn_res['verdict'].upper()}] (Passed: {tn_ok})"
    )

    large_inject_ns = max(int(base_median_ns * 0.08), 200)
    print(f"  Collecting large injection (+{large_inject_ns:,} ns, ~8% target)...")
    large_inj = _collect_medians(adapter, bench_name, reps, iters, warmup, inject_ns=large_inject_ns)
    large_res = compare_distributions(base_a, large_inj, min_noise_floor_pct=min_noise_floor_pct)
    large_flagged = large_res["verdict"] == "flag"
    print(
        f"  -> Large Injection: shift={large_res['shift_pct']:+.2f}%, "
        f"p={large_res['p_value']:.3e} [Verdict: {large_res['verdict'].upper()}] (Passed: {large_flagged})"
    )

    small_inject_ns = max(int(base_median_ns * 0.01), 25)
    print(f"  Collecting small injection (+{small_inject_ns:,} ns, ~1% target)...")
    small_inj = _collect_medians(adapter, bench_name, reps, iters, warmup, inject_ns=small_inject_ns)
    small_res = compare_distributions(base_a, small_inj, min_noise_floor_pct=min_noise_floor_pct)
    small_target_pct = 100.0 * small_inject_ns / base_median_ns
    small_detectable = bool(
        small_res["noise_floor_pct"] < small_target_pct
        and abs(small_res["shift_pct"]) <= 3.0 * small_target_pct
    )
    small_gated = (small_res["verdict"] == "ok") or small_detectable
    floor_pos = "below" if small_detectable else "above"
    print(
        f"  -> Small Injection: shift={small_res['shift_pct']:+.2f}%, "
        f"floor={small_res['noise_floor_pct']:.2f}% [Verdict: {small_res['verdict'].upper()}] "
        f"(Passed: {small_gated}; injected {small_target_pct:.2f}%, floor {floor_pos} it)"
    )

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
    """Validate that the canary drift detector catches injected SHA-256 workload drift."""
    print("[Canary Validation] Testing canary host-drift detector...")
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

    normal_ok = res_normal["status"] == "OK"
    drift_caught = res_drifted["status"] == "ENVIRONMENT_SUSPECT"

    print(f"  -> Normal canary: shift={res_normal['shift_pct']:+.2f}% [Status: {res_normal['status']}] (Passed: {normal_ok})")
    print(
        f"  -> Injected +25% extra SHA-256 work: shift={res_drifted['shift_pct']:+.2f}% "
        f"[Status: {res_drifted['status']}] (Passed: {drift_caught})"
    )

    passed = normal_ok and drift_caught
    print(f"  Canary Validation: {'PASSED' if passed else 'FAILED'}\n")
    return passed
