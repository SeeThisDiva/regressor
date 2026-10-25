"""
adapters/pymicro_adapter.py
A small, explicitly-labelled stand-in adapter that times Python stdlib operations.

Purpose: exercise the harness and statistics end-to-end on any machine (no Rust/Go
toolchain needed). It is NOT a benchmark of any real project.

"Builds" are simulated: each commit/variant maps to an amount of extra real work
(busy-wait ns per iteration) via `variant_extra_ns`. That gives a known ground truth
for testing interleaving and bisection, while every timing is still a real
measurement taken on this machine. No noise is synthesized.
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from adapters.base import BaseAdapter, busy_wait_ns
from core.models import BuildResult

_PAYLOAD = b'{"id": 48213, "service": "auth", "status": "success", "ip": "10.0.4.18"}'


class PyMicroAdapter(BaseAdapter):
    def __init__(self, variant_extra_ns: Optional[Dict[str, int]] = None):
        self.variant_extra_ns = dict(variant_extra_ns or {})

    def list_benchmarks(self) -> List[str]:
        return ["json_loads", "sha256_small"]

    def build(self, commit_ref: str, workdir: Optional[Path] = None) -> BuildResult:
        # Nothing to compile; the artifact is just the variant name.
        return BuildResult(ok=True, seconds=0.0, log_tail="simulated build", artifact=commit_ref)

    def run(self, bench_name: str, iters: int = 1500, warmup: int = 150,
            inject_ns: int = 0, artifact: Optional[str] = None) -> List[float]:
        extra = inject_ns + self.variant_extra_ns.get(artifact or "", 0)
        if bench_name == "json_loads":
            op = lambda: json.loads(_PAYLOAD)
        elif bench_name == "sha256_small":
            op = lambda: hashlib.sha256(_PAYLOAD).digest()
        else:
            raise ValueError(f"unknown benchmark {bench_name!r}")

        for _ in range(warmup):
            op()
        # Time in batches of 8 ops so sub-100ns injections (~1% of a ~3us op) are not
        # quantized to a 5x jump by 100ns timer ticks and perf_counter_ns() call overhead.
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
