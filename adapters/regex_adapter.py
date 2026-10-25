"""
adapters/regex_adapter.py
Adapter for rust-lang/regex using the noise-bench Rust timing binary.

There is deliberately no Python fallback: if the Rust binary has not been built,
run() raises. Silently substituting a different workload would make results
meaningless while looking real.
"""

import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import List, Optional

from adapters.base import BaseAdapter
from core.models import BuildResult
from core.samples import parse_samples

ROOT_DIR = Path(__file__).resolve().parent.parent


class RegexAdapter(BaseAdapter):
    def __init__(self, noise_bench_dir: Optional[str] = None, regex_repo_dir: Optional[str] = None):
        self.noise_bench_dir = Path(noise_bench_dir or ROOT_DIR / "noise-bench").resolve()
        self.regex_repo_dir = Path(regex_repo_dir or ROOT_DIR / "regex").resolve()
        self.bin_name = "noise-bench.exe" if platform.system() == "Windows" else "noise-bench"
        self.bin_path = self.noise_bench_dir / "target" / "release" / self.bin_name

    def list_benchmarks(self) -> List[str]:
        return ["find_iter_userid", "is_match_status", "compile_moderate"]

    def _sh(self, cmd, cwd, env=None, timeout=1800):
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env, timeout=timeout)
        return p.returncode, p.stdout + p.stderr

    def build(self, commit_ref: str, workdir: Optional[Path] = None) -> BuildResult:
        t0 = time.monotonic()
        from core.bisect import validate_git_ref
        try:
            validate_git_ref(commit_ref)
        except ValueError as exc:
            return BuildResult(ok=False, seconds=0.0, log_tail=str(exc))

        for tool in ("git", "cargo"):
            if not shutil.which(tool):
                return BuildResult(ok=False, seconds=0.0, log_tail=f"'{tool}' not found on PATH")
        if not (self.regex_repo_dir / ".git").exists():
            return BuildResult(ok=False, seconds=0.0,
                               log_tail=f"regex clone not found at {self.regex_repo_dir}")

        if workdir is None:
            # Legacy in-place mode: checkout and build in the shared tree. noise-bench/Cargo.toml
            # depends on `../regex`, so this only builds the right source when the clone IS that
            # directory; with any other --repo it would silently benchmark the wrong code.
            expected = (self.noise_bench_dir.parent / "regex").resolve()
            if self.regex_repo_dir != expected:
                return BuildResult(ok=False, seconds=0.0,
                                   log_tail=f"in-place build needs the clone at {expected} (got {self.regex_repo_dir}); "
                                            "pass a workdir for isolated builds instead")
            rc, out = self._sh(["git", "checkout", "--quiet", "--force", "--detach", commit_ref], self.regex_repo_dir)
            if rc != 0:
                return BuildResult(ok=False, seconds=round(time.monotonic() - t0, 2), log_tail=out[-2000:])
            rc, out = self._sh(["cargo", "build", "--release"], self.noise_bench_dir)
            artifact = str(self.bin_path)
        else:
            # Isolated mode: one git worktree + one target dir per commit, so both
            # binaries exist at once and can be run in alternation.
            rc, sha = self._sh(["git", "rev-parse", "--verify", f"{commit_ref}^{{commit}}"], self.regex_repo_dir)
            if rc != 0:
                return BuildResult(ok=False, seconds=0.0, log_tail=sha[-2000:])
            sha = sha.strip()
            root = Path(workdir).resolve() / sha[:12]
            src = root / "regex"
            bench = root / "noise-bench"
            if not src.exists():
                self._sh(["git", "worktree", "prune"], self.regex_repo_dir)
                rc, out = self._sh(["git", "worktree", "add", "--force", "--detach", str(src), sha], self.regex_repo_dir)
                if rc != 0:
                    return BuildResult(ok=False, seconds=round(time.monotonic() - t0, 2), log_tail=out[-2000:])
            bench.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.noise_bench_dir / "Cargo.toml", bench / "Cargo.toml")
            # Same lockfile for every build: otherwise cargo may resolve different transitive
            # crate versions (memchr, aho-corasick) for the two commits and confound the A/B.
            lock = self.noise_bench_dir / "Cargo.lock"
            if lock.exists() and not (bench / "Cargo.lock").exists():
                shutil.copy2(lock, bench / "Cargo.lock")
            shutil.copytree(self.noise_bench_dir / "src", bench / "src", dirs_exist_ok=True)
            env = dict(os.environ, CARGO_TARGET_DIR=str(root / "target"))
            # Cargo.toml depends on regex = { path = "../regex" }, which resolves to `src`.
            rc, out = self._sh(["cargo", "build", "--release"], bench, env=env)
            artifact = str(root / "target" / "release" / self.bin_name)

        tail = "\n".join(out.splitlines()[-25:])
        return BuildResult(ok=(rc == 0), seconds=round(time.monotonic() - t0, 2),
                           log_tail=tail, artifact=artifact if rc == 0 else None)

    def run(self, bench_name: str, iters: int = 2000, warmup: int = 200,
            inject_ns: int = 0, artifact: Optional[str] = None) -> List[float]:
        binary = Path(artifact) if artifact else self.bin_path
        if not binary.exists():
            raise FileNotFoundError(
                f"noise-bench binary not found at {binary}. Build it first "
                f"(requires Rust + a clone of rust-lang/regex). There is no Python fallback."
            )
        cmd = [str(binary), bench_name, str(iters), str(warmup), str(inject_ns), "--format=raw"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if res.returncode != 0:
            raise RuntimeError(f"Regex benchmark {bench_name} failed: {res.stderr}")
        return parse_samples(res.stdout, expected=iters, source=f"{binary.name} {bench_name}")
