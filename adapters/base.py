"""
adapters/base.py
Adapter contract decoupling the statistical engine from specific languages and build systems.

To add support for a new project or language:
1. Subclass `BaseAdapter` and implement `list_benchmarks()`, `build()`, and `run()`.
2. Support isolated builds when `workdir` is provided so two commits can be benchmarked
   in alternation (`compare-interleaved`, `bisect`).
3. Support `inject_ns` in `run()` using real CPU work (e.g., `busy_wait_ns`) so
   `regressor validate-adapter` can verify sensitivity end to end.
"""

import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

# Ensure core/ is importable when adapter modules are invoked directly.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.models import BuildResult


def busy_wait_ns(ns: int) -> None:
    """Spin for `ns` nanoseconds of wall time for ground-truth slowdown injection.

    Using real CPU work ensures injected delays experience the same scheduling and
    frequency noise as the benchmark itself.
    """
    if ns <= 0:
        return
    end = time.perf_counter_ns() + ns
    while time.perf_counter_ns() < end:
        pass


class BaseAdapter(ABC):
    """Abstract benchmark adapter interface."""

    @abstractmethod
    def list_benchmarks(self) -> List[str]:
        """Return the list of available benchmark identifiers."""

    @abstractmethod
    def build(self, commit_ref: str, workdir: Optional[Path] = None) -> BuildResult:
        """Build the benchmark at `commit_ref`.

        When `workdir` is given, the build must be isolated (separate source tree and
        target directory) and `BuildResult.artifact` must identify the built binary so
        two commits can be benchmarked in alternation.
        """

    @abstractmethod
    def run(
        self,
        bench_name: str,
        iters: int,
        warmup: int,
        inject_ns: int = 0,
        artifact: Optional[str] = None,
    ) -> List[float]:
        """Run one benchmark repetition (single process) and return per-iteration ns timings.

        Args:
            bench_name: Benchmark identifier from `list_benchmarks()`.
            iters: Number of timed iterations to execute.
            warmup: Number of untimed warmup iterations before measurement.
            inject_ns: Extra busy-wait nanoseconds added per iteration for validation.
            artifact: Build artifact identifier from `BuildResult.artifact` (or default).
        """
