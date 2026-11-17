"""
core/canary.py
Invariant canary benchmark for automated host/hypervisor environment drift detection.

Runs an invariant SHA-256 workload alongside real benchmarks. If the canary's
median latency shifts beyond the allowed noise band, the window is tagged as
ENVIRONMENT_SUSPECT, catching clock or CPU drift that static metadata misses.
"""

import hashlib
import time
from typing import Any, Dict, List

import numpy as np


class CanaryBenchmark:
    """Fixed, deterministic workload whose code and input never change between runs.

    Any measured latency shift is attributable to external host or VM noise.
    """

    @staticmethod
    def run_sample(iters: int = 8000, inject_jitter_pct: float = 0.0) -> float:
        """Run a fixed SHA-256 loop and return elapsed nanoseconds.

        When ``inject_jitter_pct > 0``, proportionally more SHA-256 iterations are run.
        """
        payload = b"canary_fixed_payload_for_host_drift_detection_perfguard_2026"
        effective_iters = int(round(iters * (1.0 + max(0.0, inject_jitter_pct) / 100.0)))
        t0 = time.perf_counter_ns()
        curr = payload
        for _ in range(effective_iters):
            curr = hashlib.sha256(curr).digest()
        return float(time.perf_counter_ns() - t0)

    @classmethod
    def run_reps(
        cls,
        reps: int = 15,
        iters: int = 8000,
        inject_jitter_pct: float = 0.0,
        warmup: int = 2,
    ) -> List[float]:
        """Run ``reps`` canary samples after discarding ``warmup`` cold samples.

        The first sample is typically 30-45% slower (cold caches, frequency ramp);
        keeping it inflates the spread estimate and blinds the drift check.
        """
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
        """Evaluate whether the candidate canary drifted relative to the baseline canary.

        Drift is triggered when ``|median shift| > max(min(multiplier * CV_MAD, max_allowed_noise_pct), min_drift_pct)``.
        Using a MAD-based spread (1.4826 * MAD / median) prevents one cold outlier from
        widening the noise band, while ``min_drift_pct`` prevents hypersensitivity on
        quiet hosts and ``max_allowed_noise_pct`` caps noisy-host tolerance.
        """
        base = np.asarray(base_canary_samples, dtype=np.float64)
        cand = np.asarray(cand_canary_samples, dtype=np.float64)

        base_med = float(np.median(base))
        cand_med = float(np.median(cand))
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
