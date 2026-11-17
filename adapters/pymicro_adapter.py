"""
adapters/pymicro_adapter.py
A lightweight stand-in adapter that times Python standard-library operations.

Purpose: exercise the harness and statistics end to end on any machine without
needing a Rust/Go toolchain. It is NOT a benchmark of any real project.

"Builds" are simulated: each commit/variant maps to an extra busy-wait delay per
iteration via `variant_extra_ns`. Every timing is a real wall-clock measurement
taken on the host; no noise is synthesized.
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from adapters.base import BaseAdapter, busy_wait_ns
from core.models import BuildResult

_PAYLOAD = b'{"id": 48213, "service": "auth", "status": "success", "ip": "10.0.4.18"}'


def _bench_json_loads() -> None:
    json.loads(_PAYLOAD)


def _bench_sha256_small() -> None:
    hashlib.sha256(_PAYLOAD).digest()


_WORKLOADS: Dict[str, Callable[[], None]] = {
    "json_loads": _bench_json_loads,
    "sha256_small": _bench_sha256_small,
}


class PyMicroAdapter(BaseAdapter):
    """Cross-platform stand-in adapter backed by real Python stdlib workloads."""

    def __init__(self, variant_extra_ns: Optional[Dict[str, int]] = None):
        self.variant_extra_ns = dict(variant_extra_ns or {})

    def list_benchmarks(self) -> List[str]:
        """Return available stand-in benchmark names."""
        return list(_WORKLOADS)

    def build(self, commit_ref: str, workdir: Optional[Path] = None) -> BuildResult:
        """Simulate a build by returning `commit_ref` as the artifact identifier."""
        return BuildResult(ok=True, seconds=0.0, log_tail="simulated build", artifact=commit_ref)

    def run(
        self,
        bench_name: str,
        iters: int = 1500,
        warmup: int = 150,
        inject_ns: int = 0,
        artifact: Optional[str] = None,
    ) -> List[float]:
        """Execute `iters` timed calls (batched by 8) plus any injected busy-wait."""
        op = _WORKLOADS.get(bench_name)
        if op is None:
            raise ValueError(f"unknown benchmark {bench_name!r}")

        extra = inject_ns + self.variant_extra_ns.get(artifact or "", 0)
        for _ in range(warmup):
            op()

        # Time in batches of 8 ops so sub-100ns injections are not quantized by
        # coarse timer ticks or perf_counter_ns() call overhead.
        batch = 8 if iters >= 8 else 1
        samples: List[float] = []
        rem = iters
        while rem > 0:
            k = min(batch, rem)
            t0 = time.perf_counter_ns()
            for _ in range(k):
                op()
            busy_wait_ns(extra * k)
            per_op = float(time.perf_counter_ns() - t0) / k
            samples.extend([per_op] * k)
            rem -= k
        return samples
