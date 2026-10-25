"""
core/canary.py
Canary benchmark runner for automated host/hypervisor environment drift detection (P4 #18).
Runs an invariant computation alongside real benchmarks. If the canary's latency drifts,
the run is tagged as ENVIRONMENT_SUSPECT, catching clock drift that CPU model strings miss.
"""

import hashlib
import time
from typing import Any, Dict, List

import numpy as np


class CanaryBenchmark:
    """
    Fixed, deterministic workload. Code and input never change between runs.
    Any measured latency shift is 100% attributable to external host/VM noise.
    """

    @staticmethod
    def run_sample(iters: int = 8000, inject_jitter_pct: float = 0.0) -> float:
        """Runs a fixed sha256 loop and returns elapsed nanoseconds.
        When `inject_jitter_pct > 0`, runs proportionally more real SHA-256 iterations."""
        payload = b"canary_fixed_payload_for_host_drift_detection_perfguard_2026"
        effective_iters = int(round(iters * (1.0 + max(0.0, inject_jitter_pct) / 100.0)))
        t0 = time.perf_counter_ns()
        curr = payload
        for _ in range(effective_iters):
            curr = hashlib.sha256(curr).digest()
        return float(time.perf_counter_ns() - t0)

    @classmethod
    def run_reps(cls, reps: int = 15, iters: int = 8000, inject_jitter_pct: float = 0.0,
                 warmup: int = 2) -> List[float]:
        """Runs `reps` canary samples (one elapsed-ns value each) after `warmup` discarded ones.
        The first sample is reliably 30-45% slower (cold caches, frequency ramp); keeping it
        inflates the spread estimate and blinds the drift check."""
        for _ in range(warmup):
            cls.run_sample(iters=iters)
        return [cls.run_sample(iters=iters, inject_jitter_pct=inject_jitter_pct) for _ in range(reps)]

    @classmethod
    def evaluate_drift(
        cls,
        base_canary_samples: List[float],
        cand_canary_samples: List[float],
        drift_threshold_multiplier: float = 2.0,
        min_drift_pct: float = 2.5,
        max_allowed_noise_pct: float = 5.0,
    ) -> Dict[str, Any]:
        """
        Check if the candidate canary shifted relative to the baseline canary.
        Drift = |median shift| > clamp(multiplier x baseline CV, min_drift_pct, max_allowed_noise_pct).
        The lower floor (default 2.5%) stops an unusually quiet baseline from making the canary
        hypersensitive; the upper cap (default 5.0%) ensures high baseline variance on a noisy
        host never blinds the canary to a >5% environment shift.
        Returns drift evaluation and status ('OK' or 'ENVIRONMENT_SUSPECT').
        """
        base = np.array(base_canary_samples, dtype=np.float64)
        cand = np.array(cand_canary_samples, dtype=np.float64)

        base_med = float(np.median(base))
        cand_med = float(np.median(cand))
        # Robust relative spread (1.4826 x MAD / median ~ sigma/median for normal data): one stray
        # sample cannot widen the allowed-noise band the way a std-based CV does.
        base_cv = float(1.4826 * np.median(np.abs(base - base_med)) / base_med) if base_med > 0 else 0.0

        shift_pct = 100.0 * (cand_med - base_med) / base_med if base_med > 0 else 0.0
        allowed_noise_pct = min(100.0 * base_cv * drift_threshold_multiplier, max_allowed_noise_pct)

        is_drifted = bool(abs(shift_pct) > max(allowed_noise_pct, min_drift_pct))

        return {
            "status": "ENVIRONMENT_SUSPECT" if is_drifted else "OK",
            "is_drifted": is_drifted,
            "shift_pct": round(shift_pct, 2),
            "base_cv_pct": round(100.0 * base_cv, 2),
            "allowed_noise_pct": round(allowed_noise_pct, 2),
            "base_median_ns": round(base_med, 1),
            "cand_median_ns": round(cand_med, 1),
        }
