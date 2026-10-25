"""
adapters/base.py
Adapter contract: decouples the framework from any specific language or project.
"""

import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

# Ensure core is importable
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.models import BuildResult


def busy_wait_ns(ns: int) -> None:
    """Spin for `ns` nanoseconds of wall time. Used for ground-truth injection:
    the injected delay is real CPU work, so it experiences the same noise as
    the benchmark itself (same approach as the Rust harness)."""
    if ns <= 0:
        return
    end = time.perf_counter_ns() + ns
    while time.perf_counter_ns() < end:
        pass


class BaseAdapter(ABC):
    @abstractmethod
    def list_benchmarks(self) -> List[str]:
        """Return list of available benchmark identifiers."""

    @abstractmethod
    def build(self, commit_ref: str, workdir: Optional[Path] = None) -> BuildResult:
        """Build the benchmark at `commit_ref`.

        If `workdir` is given, the build must be isolated (its own source tree and
        target dir) and `BuildResult.artifact` must point at the resulting binary,
        so that two commits can be benchmarked in alternation.
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
        """Run one benchmark rep (one process) and return per-iteration ns timings.

        artifact:  which build to run (from BuildResult.artifact); None = default build.
        inject_ns: real busy-wait added to every iteration, for ground-truth validation.
        """
