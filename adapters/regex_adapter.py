"""
adapters/regex_adapter.py
Adapter for rust-lang/regex using the `noise-bench` Rust timing binary.

There is deliberately no Python fallback: if the Rust binary has not been built,
`run()` raises `FileNotFoundError`. Silently substituting a different workload would
produce misleading results that still look real.
"""

import os
import platform
import shutil
import subprocess
import time
import tomllib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from adapters.base import ROOT_DIR, BaseAdapter
from core.bisect import validate_git_ref
from core.models import BuildResult
from core.samples import parse_samples

_BENCHMARKS = (
    "find_iter_userid",
    "is_match_status",
    "compile_moderate",
    "rebar_curated_01_literal_sherlock_en",
    "rebar_curated_01_literal_sherlock_casei_en",
    "rebar_curated_02_literal_alternate_sherlock_en",
    "rebar_curated_02_literal_alternate_sherlock_casei_ru",
    "rebar_curated_03_date_unicode",
    "rebar_curated_04_ruff_noqa_real",
    "rebar_curated_04_ruff_noqa_tweaked_lite",
    "rebar_curated_05_lexer_veryl_single",
    "rebar_curated_05_lexer_veryl_regexset",
    "rebar_curated_06_cloudflare_redos_long",
    "rebar_curated_08_words_all_russian",
    "rebar_curated_09_aws_keys_quick",
    "rebar_curated_10_bounded_repeat_letters_ru",
    "rebar_curated_10_bounded_repeat_context",
    "rebar_curated_12_dictionary_single",
    "rebar_opt_onepass_first_three_words_en",
    "rebar_opt_backtrack_words_en",
    "rebar_opt_reverse_suffix_holmes",
    "rebar_opt_reverse_inner_email",
    "rebar_reported_i988_sql_injection_compile",
    "rebar_unicode_compile_one_letter",
    "rebar_wild_rustsec_cargo_audit_bytes",
)


def _sync_file_if_changed(src: Path, dst: Path) -> bool:
    """Copy ``src`` to ``dst`` only when missing or content differs; return True if updated."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        try:
            if src.read_bytes() == dst.read_bytes():
                return False
        except OSError:
            pass
    shutil.copy2(src, dst)
    return True


def _sync_tree(src_dir: Path, dst_dir: Path) -> None:
    """Synchronize ``src_dir`` into ``dst_dir`` without touching unchanged files."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    expected = set()
    for src_path in src_dir.rglob("*"):
        rel = src_path.relative_to(src_dir)
        dst_path = dst_dir / rel
        if src_path.is_dir():
            dst_path.mkdir(parents=True, exist_ok=True)
            expected.add(rel)
        elif src_path.is_file():
            expected.add(rel)
            _sync_file_if_changed(src_path, dst_path)

    for existing in sorted(dst_dir.rglob("*"), reverse=True):
        rel = existing.relative_to(dst_dir)
        if rel not in expected:
            if existing.is_file() or existing.is_symlink():
                existing.unlink()
            elif existing.is_dir():
                try:
                    existing.rmdir()
                except OSError:
                    pass


class RegexAdapter(BaseAdapter):
    """Builds and runs `noise-bench` against a local `rust-lang/regex` git clone."""

    def __init__(
        self,
        noise_bench_dir: Optional[str] = None,
        regex_repo_dir: Optional[str] = None,
        project_toml: Optional[str] = None,
    ):
        self.noise_bench_dir = Path(noise_bench_dir or ROOT_DIR / "noise-bench").resolve()
        self.regex_repo_dir = Path(regex_repo_dir or ROOT_DIR / "regex").resolve()
        self.project_toml = Path(project_toml or ROOT_DIR / "projects" / "regex.toml").resolve()
        self.bin_name = "noise-bench.exe" if platform.system() == "Windows" else "noise-bench"
        self.bin_path = self.noise_bench_dir / "target" / "release" / self.bin_name

    def list_benchmarks(self) -> List[str]:
        """Return configured benchmarks from ``projects/regex.toml`` (or binary/fallback)."""
        if self.project_toml.exists():
            raw = tomllib.loads(self.project_toml.read_text(encoding="utf-8"))
            benches = raw.get("benchmarks")
            if isinstance(benches, list) and benches and all(isinstance(b, str) and b for b in benches):
                return list(benches)
        if self.bin_path.exists():
            return self.query_binary_benchmarks()
        return list(_BENCHMARKS)

    def query_binary_benchmarks(self, artifact: Optional[str] = None) -> List[str]:
        """Query the compiled `noise-bench` binary via `--list-benchmarks`."""
        binary = Path(artifact) if artifact else self.bin_path
        if not binary.exists():
            raise FileNotFoundError(
                f"noise-bench binary not found at {binary}. Build it first "
                f"(requires Rust + a clone of rust-lang/regex). There is no Python fallback."
            )
        res = subprocess.run([str(binary), "--list-benchmarks"], capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            raise RuntimeError(f"Failed to list benchmarks from {binary}: {res.stderr}")
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]

    def _sh(
        self,
        cmd: List[str],
        cwd: Path,
        env: Optional[Dict[str, str]] = None,
        timeout: int = 1800,
    ) -> Tuple[int, str]:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env, timeout=timeout)
        return p.returncode, p.stdout + p.stderr

    @staticmethod
    def _elapsed_seconds(t0: float) -> float:
        return round(time.monotonic() - t0, 2)

    def _check_build_prerequisites(self, commit_ref: str) -> Optional[str]:
        """Validate the git ref, required toolchain binaries, and local git clone."""
        try:
            validate_git_ref(commit_ref)
        except ValueError as exc:
            return str(exc)

        for tool in ("git", "cargo"):
            if not shutil.which(tool):
                return f"'{tool}' not found on PATH"
        if not (self.regex_repo_dir / ".git").exists():
            return f"regex clone not found at {self.regex_repo_dir}"
        return None

    def _run_cargo_build(
        self,
        cwd: Path,
        artifact: str,
        t0: float,
        env: Optional[Dict[str, str]] = None,
    ) -> BuildResult:
        """Compile `noise-bench` in release mode and return a structured `BuildResult`."""
        rc, out = self._sh(["cargo", "build", "--release"], cwd, env=env)
        tail = "\n".join(out.splitlines()[-25:])
        return BuildResult(
            ok=(rc == 0),
            seconds=self._elapsed_seconds(t0),
            log_tail=tail,
            artifact=artifact if rc == 0 else None,
        )

    def _build_in_place(self, commit_ref: str, t0: float) -> BuildResult:
        """Check out `commit_ref` in the shared clone and build in `noise_bench_dir`."""
        # noise-bench/Cargo.toml points to `../regex`, so an in-place build only compiles
        # the expected code when regex_repo_dir sits right beside noise_bench_dir.
        expected = (self.noise_bench_dir.parent / "regex").resolve()
        if self.regex_repo_dir != expected:
            return BuildResult(
                ok=False,
                seconds=0.0,
                log_tail=(
                    f"in-place build needs the clone at {expected} (got {self.regex_repo_dir}); "
                    "pass a workdir for isolated builds instead"
                ),
            )
        rc, out = self._sh(["git", "checkout", "--quiet", "--force", "--detach", commit_ref], self.regex_repo_dir)
        if rc != 0:
            return BuildResult(ok=False, seconds=self._elapsed_seconds(t0), log_tail=out[-2000:])
        return self._run_cargo_build(self.noise_bench_dir, str(self.bin_path), t0)

    def _build_isolated(self, commit_ref: str, workdir: Path, t0: float) -> BuildResult:
        """Create an isolated git worktree + cargo target dir so two builds can run alternately."""
        rc, sha = self._sh(["git", "rev-parse", "--verify", f"{commit_ref}^{{commit}}"], self.regex_repo_dir)
        if rc != 0:
            return BuildResult(ok=False, seconds=0.0, log_tail=sha[-2000:])

        root = Path(workdir).resolve() / sha.strip()[:12]
        src = root / "regex"
        bench = root / "noise-bench"
        if not src.exists():
            self._sh(["git", "worktree", "prune"], self.regex_repo_dir)
            rc, out = self._sh(["git", "worktree", "add", "--force", "--detach", str(src), sha.strip()], self.regex_repo_dir)
            if rc != 0:
                return BuildResult(ok=False, seconds=self._elapsed_seconds(t0), log_tail=out[-2000:])

        bench.mkdir(parents=True, exist_ok=True)
        cargo_changed = _sync_file_if_changed(self.noise_bench_dir / "Cargo.toml", bench / "Cargo.toml")
        # Pin the same Cargo.lock across commits so transitive crate resolution stays identical,
        # refreshing it only if Cargo.toml itself changed (e.g., new dependencies added).
        lock = self.noise_bench_dir / "Cargo.lock"
        if lock.exists() and (cargo_changed or not (bench / "Cargo.lock").exists()):
            shutil.copy2(lock, bench / "Cargo.lock")
        _sync_tree(self.noise_bench_dir / "src", bench / "src")
        haystacks_dir = self.noise_bench_dir / "haystacks"
        if haystacks_dir.is_dir():
            _sync_tree(haystacks_dir, bench / "haystacks")

        env = dict(os.environ, CARGO_TARGET_DIR=str(root / "target"))
        artifact = str(root / "target" / "release" / self.bin_name)
        return self._run_cargo_build(bench, artifact, t0, env=env)

    def build(self, commit_ref: str, workdir: Optional[Path] = None) -> BuildResult:
        """Build `noise-bench` for `commit_ref`, isolated in `workdir` if provided."""
        t0 = time.monotonic()
        err = self._check_build_prerequisites(commit_ref)
        if err:
            return BuildResult(ok=False, seconds=0.0, log_tail=err)
        if workdir is None:
            return self._build_in_place(commit_ref, t0)
        return self._build_isolated(commit_ref, workdir, t0)

    def run(
        self,
        bench_name: str,
        iters: int = 2000,
        warmup: int = 200,
        inject_ns: int = 0,
        artifact: Optional[str] = None,
    ) -> List[float]:
        """Run one repetition of `noise-bench` and return per-iteration timings in ns."""
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
