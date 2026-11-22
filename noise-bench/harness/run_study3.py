#!/usr/bin/env python3
"""
Resumable, crash-safe Study 3 benchmark driver for `rust-lang/regex`.

Builds `noise-bench` for every commit in an isolated git worktree (placed outside
cloud-synced directories by default), runs all configured benchmarks for N
independent process repetitions pinned to a single P-core at high process
priority, logs invariant SHA-256 canary samples before and after each commit,
and persists commit metadata and per-run medians into SQLite via `core.db`.
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import json
import os
import platform
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]

HARNESS_DIR = Path(__file__).resolve().parent
NOISE_BENCH_DIR = HARNESS_DIR.parent
REPO_ROOT = NOISE_BENCH_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import adapters.regex_adapter as regex_adapter_mod  # noqa: E402
from adapters.regex_adapter import RegexAdapter  # noqa: E402
from core.canary import CanaryBenchmark  # noqa: E402
from core.db import Database  # noqa: E402

DEFAULT_COMMITS_FILE = HARNESS_DIR / "commits_study3.txt"
DEFAULT_COMMITS_META = HARNESS_DIR / "commits_study3.json"
DEFAULT_DB_PATH = NOISE_BENCH_DIR / "results" / "study3" / "study3.db"
DEFAULT_RESULTS_DIR = NOISE_BENCH_DIR / "results" / "study3_commits"
DEFAULT_CHECKPOINT_PATH = NOISE_BENCH_DIR / "results" / "study3" / "checkpoint.json"
DEFAULT_LOG_DIR = NOISE_BENCH_DIR / "logs"
DEFAULT_WORKDIR = Path(tempfile.gettempdir()) / "regressor-study3-builds"
PORTABLE_STUDY3_DATA = "data/regex_study3_history.json.gz"


class MissingStudy3RawDataError(FileNotFoundError):
    """Raised when resuming Study 3 without retained raw outputs and working DB."""


def _require_psutil() -> Any:
    if psutil is None:
        raise RuntimeError("psutil is required for pinned Study 3 runs; install it with `pip install psutil`.")
    return psutil


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rel_to_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _atomic_write_json(path: Path, payload: Any) -> None:
    _atomic_write_text(path, json.dumps(payload, indent=2) + "\n")


def _append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, separators=(",", ":")) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _cpu_model() -> str:
    if platform.system() == "Linux":
        try:
            with open("/proc/cpuinfo", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
    return platform.processor() or "unknown"


def _tool_version(cmd: Sequence[str]) -> str:
    try:
        proc = subprocess.run(list(cmd), capture_output=True, text=True, timeout=30)
        return proc.stdout.strip() if proc.returncode == 0 else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "not installed"


def _windows_core_topology() -> List[Tuple[int, List[int]]]:
    """Return `[(efficiency_class, [logical_cpu_ids]), ...]` via Windows kernel32."""
    import ctypes
    import ctypes.wintypes as wintypes

    class GROUP_AFFINITY(ctypes.Structure):
        _fields_ = [
            ("Mask", ctypes.c_size_t),
            ("Group", wintypes.WORD),
            ("Reserved", wintypes.WORD * 3),
        ]

    class PROCESSOR_RELATIONSHIP(ctypes.Structure):
        _fields_ = [
            ("Flags", ctypes.c_byte),
            ("EfficiencyClass", ctypes.c_byte),
            ("Reserved", ctypes.c_byte * 20),
            ("GroupCount", wintypes.WORD),
            ("GroupMask", GROUP_AFFINITY * 1),
        ]

    class SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX(ctypes.Structure):
        _fields_ = [
            ("Relationship", wintypes.DWORD),
            ("Size", wintypes.DWORD),
            ("Processor", PROCESSOR_RELATIONSHIP),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    length = wintypes.DWORD(0)
    k32.GetLogicalProcessorInformationEx(0, None, ctypes.byref(length))
    if length.value == 0:
        return []
    buf = ctypes.create_string_buffer(length.value)
    if not k32.GetLogicalProcessorInformationEx(0, buf, ctypes.byref(length)):
        return []

    cores: List[Tuple[int, List[int]]] = []
    offset = 0
    while offset < length.value:
        ptr = ctypes.cast(
            ctypes.byref(buf, offset),
            ctypes.POINTER(SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX),
        )
        info = ptr.contents
        mask = info.Processor.GroupMask[0].Mask
        cpus = [i for i in range(64) if mask & (1 << i)]
        cores.append((int(info.Processor.EfficiencyClass), cpus))
        offset += info.Size
    return cores


def detect_p_core_cpu(explicit_cpu: Optional[int] = None) -> Dict[str, Any]:
    """Select one P-core logical CPU ID and describe the host topology."""
    ps = _require_psutil()
    avail = ps.Process().cpu_affinity() or list(range(os.cpu_count() or 1))
    if explicit_cpu is not None:
        if explicit_cpu not in avail:
            raise ValueError(f"Requested CPU {explicit_cpu} is not in available affinity {avail}")
        return {"cpu_id": explicit_cpu, "method": "explicit", "efficiency_class": None}

    if platform.system() == "Windows":
        try:
            cores = _windows_core_topology()
            if cores:
                max_eff = max(eff for eff, _ in cores)
                p_cores = [cpus for eff, cpus in cores if eff == max_eff and cpus]
                # Prefer the second P-core (index 1) to avoid OS timer/DPC interrupts on CPU 0.
                chosen_core = p_cores[1] if len(p_cores) > 1 else p_cores[0]
                for cpu in chosen_core:
                    if cpu in avail:
                        return {
                            "cpu_id": cpu,
                            "method": "windows_efficiency_class",
                            "efficiency_class": max_eff,
                            "p_core_count": len(p_cores),
                            "core_siblings": chosen_core,
                        }
        except OSError:
            pass

    fallback = avail[2] if len(avail) > 2 else avail[0]
    return {"cpu_id": fallback, "method": "fallback", "efficiency_class": None}


class PinnedExecutionContext:
    """Pin Python process + spawned `RegexAdapter` children to one P-core at high priority."""

    def __init__(self, cpu_id: int, high_priority: bool = True) -> None:
        self.cpu_id = int(cpu_id)
        self.high_priority = bool(high_priority)
        self._proc = _require_psutil().Process()
        self._orig_affinity: Optional[List[int]] = None
        self._orig_nice: Optional[int] = None
        self._orig_subprocess_run = None
        self.priority_label = "NORMAL"

    def __enter__(self) -> "PinnedExecutionContext":
        self._orig_affinity = list(self._proc.cpu_affinity())
        self._orig_nice = int(self._proc.nice())
        self._proc.cpu_affinity([self.cpu_id])

        if self.high_priority:
            if platform.system() == "Windows":
                high = getattr(psutil, "HIGH_PRIORITY_CLASS", 0x80)
                self._proc.nice(high)
                self.priority_label = "HIGH_PRIORITY_CLASS"
            else:
                try:
                    self._proc.nice(-10)
                    self.priority_label = "NICE_-10"
                except (psutil.AccessDenied, PermissionError, OSError):
                    self.priority_label = f"NICE_{self._orig_nice}"

        # On Windows, CreateProcess resets child priority to NORMAL unless creationflags is set.
        if platform.system() == "Windows" and self.high_priority:
            orig_run = regex_adapter_mod.subprocess.run
            high_flag = getattr(subprocess, "HIGH_PRIORITY_CLASS", 0x80)

            def _high_prio_run(*args: Any, **kwargs: Any) -> Any:
                kwargs.setdefault("creationflags", 0)
                kwargs["creationflags"] |= high_flag
                return orig_run(*args, **kwargs)

            self._orig_subprocess_run = orig_run
            regex_adapter_mod.subprocess.run = _high_prio_run
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._orig_subprocess_run is not None:
            regex_adapter_mod.subprocess.run = self._orig_subprocess_run
            self._orig_subprocess_run = None
        if self._orig_nice is not None:
            with contextlib.suppress(psutil.Error, OSError):
                self._proc.nice(self._orig_nice)
        if self._orig_affinity is not None:
            with contextlib.suppress(psutil.Error, OSError):
                self._proc.cpu_affinity(self._orig_affinity)


def verify_child_pinning(cpu_id: int, high_priority: bool) -> Dict[str, Any]:
    """Spawn a probe child inside `PinnedExecutionContext` and confirm affinity and priority."""
    with PinnedExecutionContext(cpu_id, high_priority=high_priority) as ctx:
        kwargs: Dict[str, Any] = {"capture_output": True, "text": True, "timeout": 15}
        if platform.system() == "Windows" and high_priority:
            kwargs["creationflags"] = getattr(subprocess, "HIGH_PRIORITY_CLASS", 0x80)
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json, psutil; p = psutil.Process(); "
                "print(json.dumps({'affinity': p.cpu_affinity(), 'nice': p.nice()}))",
            ],
            **kwargs,
        )
        child_info = json.loads(probe.stdout.strip()) if probe.returncode == 0 else {}
        return {
            "parent_affinity": [int(x) for x in ctx._proc.cpu_affinity()],
            "parent_nice": int(ctx._proc.nice()),
            "priority_label": ctx.priority_label,
            "child_affinity": child_info.get("affinity"),
            "child_nice": child_info.get("nice"),
        }


def resolve_commit_meta(regex_repo: Path, ref: str) -> Dict[str, str]:
    """Resolve SHA, author_date, and subject for `ref` inside `regex_repo`."""
    sha = subprocess.check_output(
        ["git", "-C", str(regex_repo), "rev-parse", "--verify", f"{ref}^{{commit}}"],
        text=True,
        encoding="utf-8",
    ).strip()
    show = subprocess.check_output(
        ["git", "-C", str(regex_repo), "show", "-s", "--format=%aI%x00%s", sha, "--"],
        text=True,
        encoding="utf-8",
    ).rstrip("\r\n")
    author_date, subject = show.split("\x00", 1)
    return {
        "sha": sha,
        "short_sha": sha[:10],
        "short7": sha[:7],
        "author_date": author_date,
        "subject": subject,
    }


def load_commit_list(
    commits_file: Path,
    commits_meta_file: Path,
    regex_repo: Path,
    explicit_commits: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Load ordered commits and attach static diff classifications if available."""
    meta_by_sha: Dict[str, Dict[str, Any]] = {}
    if commits_meta_file.exists():
        raw_meta = json.loads(commits_meta_file.read_text(encoding="utf-8"))
        for c in raw_meta.get("commits", []):
            meta_by_sha[c["sha"]] = c
            meta_by_sha[c["short_sha"]] = c
            meta_by_sha[c["short7"]] = c

    refs = (
        explicit_commits
        if explicit_commits
        else [ln.strip() for ln in commits_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    )

    out: List[Dict[str, Any]] = []
    for idx, ref in enumerate(refs, start=1):
        cached = meta_by_sha.get(ref)
        if cached and all(k in cached for k in ("sha", "short_sha", "short7", "author_date", "subject")):
            resolved = {
                "sha": cached["sha"],
                "short_sha": cached["short_sha"],
                "short7": cached["short7"],
                "author_date": cached["author_date"],
                "subject": cached["subject"],
            }
            extra = cached
        else:
            resolved = resolve_commit_meta(regex_repo, ref)
            extra = meta_by_sha.get(resolved["sha"]) or meta_by_sha.get(ref) or {}
        out.append({
            "index": idx,
            **resolved,
            "touches_src": bool(extra.get("touches_src", False)),
            "is_doc_or_comment_only": bool(extra.get("is_doc_or_comment_only", False)),
            "is_null_control": bool(extra.get("is_null_control", False)),
            "diff_classification": extra.get("diff_classification", "unspecified"),
        })
    return out


def load_benchmark_params(
    adapter: RegexAdapter,
    project_toml_path: Path,
    default_iters: int,
    default_warmup: int,
    iters_config_path: Optional[Path] = None,
    only_benchmarks: Optional[List[str]] = None,
) -> Tuple[List[str], Dict[str, Tuple[int, int]], Dict[str, Any]]:
    """Determine benchmark list and per-benchmark `(iters, warmup)` counts."""
    raw_toml = tomllib.loads(project_toml_path.read_text(encoding="utf-8"))
    benches = list(only_benchmarks) if only_benchmarks else list(adapter.list_benchmarks())

    overrides: Dict[str, Dict[str, int]] = {}
    # Optional table in regex.toml or external JSON file.
    for key in ("benchmark_params", "benchmark_iters", "study3"):
        section = raw_toml.get(key)
        if isinstance(section, dict):
            for b, cfg in section.items():
                if isinstance(cfg, dict):
                    overrides[b] = cfg
    if iters_config_path and iters_config_path.exists():
        ext = json.loads(iters_config_path.read_text(encoding="utf-8"))
        for b, cfg in ext.items():
            if isinstance(cfg, dict):
                overrides[b] = cfg

    params: Dict[str, Tuple[int, int]] = {}
    for b in benches:
        cfg = overrides.get(b, {})
        params[b] = (
            int(cfg.get("iters", default_iters)),
            int(cfg.get("warmup", default_warmup)),
        )
    return benches, params, raw_toml


def cleanup_commit_workdir(regex_repo: Path, workdir: Path, sha: str) -> None:
    """Remove the isolated git worktree and Cargo target dir for `sha`."""
    commit_root = Path(workdir).resolve() / sha[:12]
    src_wt = commit_root / "regex"
    if src_wt.exists():
        subprocess.run(
            ["git", "-C", str(regex_repo), "worktree", "remove", "--force", str(src_wt)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    if commit_root.exists():
        shutil.rmtree(commit_root, ignore_errors=True)
    subprocess.run(
        ["git", "-C", str(regex_repo), "worktree", "prune"],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _is_commit_already_complete(
    db: Database,
    proj_id: int,
    commit_dir: Path,
    sha: str,
    benches: List[str],
    reps: int,
) -> bool:
    """Return True iff `meta.json` and SQLite both show complete results for `sha`."""
    meta_path = commit_dir / "meta.json"
    if not meta_path.exists():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    status = meta.get("status")
    if status == "build_failed":
        row = db.find_commit_by_prefix(sha, project_id=proj_id)
        return row is not None and not bool(row["build_ok"])

    if status != "complete":
        return False

    row = db.find_commit_by_prefix(sha, project_id=proj_id)
    if row is None or not bool(row["build_ok"]):
        return False

    runs_by_bench = db.get_commit_runs_by_benchmark(row["id"])
    return all(len(runs_by_bench.get(b, [])) >= reps for b in benches)


def _summarize_canary(
    before_samples: List[float],
    after_samples: List[float],
    prev_after: Optional[List[float]],
    anchor_before: Optional[List[float]],
) -> Dict[str, Any]:
    within = CanaryBenchmark.evaluate_drift(before_samples, after_samples)
    vs_prev = CanaryBenchmark.evaluate_drift(prev_after, before_samples) if prev_after else None
    vs_anchor = CanaryBenchmark.evaluate_drift(anchor_before, before_samples) if anchor_before else None
    return {
        "reps": len(before_samples),
        "iters": 8000,
        "warmup": 2,
        "before_samples_ns": [round(float(x), 1) for x in before_samples],
        "after_samples_ns": [round(float(x), 1) for x in after_samples],
        "within_commit": within,
        "vs_prev_commit": vs_prev,
        "vs_anchor_commit": vs_anchor,
    }


def _save_raw_samples(
    commit_dir: Path,
    bench: str,
    rep_samples: List[List[float]],
    raw_format: str,
) -> str:
    """Save raw per-iteration durations outside the timing window and return relative path."""
    if raw_format == "none":
        return ""
    commit_dir.mkdir(parents=True, exist_ok=True)
    if raw_format == "txt":
        last_path = commit_dir / f"{bench}_rep{len(rep_samples):03d}.txt"
        for idx, samples in enumerate(rep_samples, start=1):
            rep_file = commit_dir / f"{bench}_rep{idx:03d}.txt"
            _atomic_write_text(rep_file, "\n".join(str(int(round(s))) for s in samples) + "\n")
        return _rel_to_repo(last_path)

    gz_path = commit_dir / f"{bench}.samples.json.gz"
    tmp_path = commit_dir / f".{bench}.samples.json.gz.tmp.{os.getpid()}"
    payload = {
        "benchmark": bench,
        "reps": [[int(round(x)) for x in rep] for rep in rep_samples],
    }
    with gzip.open(tmp_path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    os.replace(tmp_path, gz_path)
    return _rel_to_repo(gz_path)


def run_baseline_session(
    adapter: RegexAdapter,
    ref: str,
    benches: List[str],
    bench_params: Dict[str, Tuple[int, int]],
    reps: int,
    outdir: Path,
    workdir: Path,
    cpu_id: int,
    high_priority: bool,
    keep_worktrees: bool,
) -> int:
    """Collect a single-session baseline (`*_repNNN.txt`) for `regressor.py evaluate-power`."""
    meta = resolve_commit_meta(adapter.regex_repo_dir, ref)
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"[baseline] Building {meta['short_sha']} ({meta['subject']}) ...", flush=True)
    build_res = adapter.build(meta["sha"], workdir=workdir)
    if not build_res.ok:
        print(f"[baseline] BUILD FAILED:\n{build_res.log_tail}", file=sys.stderr)
        return 1

    try:
        with PinnedExecutionContext(cpu_id, high_priority=high_priority):
            canary_pre = CanaryBenchmark.run_reps(reps=15, iters=8000, warmup=2)
            t0 = time.monotonic()
            all_raw: Dict[str, List[List[float]]] = {}
            for bench in benches:
                iters, warmup = bench_params[bench]
                b_reps: List[List[float]] = []
                for _ in range(reps):
                    b_reps.append(adapter.run(bench, iters=iters, warmup=warmup, artifact=build_res.artifact))
                all_raw[bench] = b_reps
                meds = [float(statistics.median(r)) for r in b_reps]
                cv = float(np.std(meds, ddof=1) / np.mean(meds) * 100.0) if len(meds) > 1 else 0.0
                print(
                    f"  [baseline] {bench:36s} med={statistics.median(meds):10.1f} ns  CV={cv:5.2f}%",
                    flush=True,
                )
            wall_s = round(time.monotonic() - t0, 2)
            canary_post = CanaryBenchmark.run_reps(reps=15, iters=8000, warmup=2)

        for bench, b_reps in all_raw.items():
            for rep_idx, samples in enumerate(b_reps, start=1):
                rep_file = outdir / f"{bench}_rep{rep_idx:03d}.txt"
                _atomic_write_text(rep_file, "\n".join(str(int(round(s))) for s in samples) + "\n")

        _atomic_write_json(
            outdir / "baseline_meta.json",
            {
                "commit": meta,
                "reps": reps,
                "cpu_id": cpu_id,
                "wall_seconds": wall_s,
                "canary_within": CanaryBenchmark.evaluate_drift(canary_pre, canary_post),
                "benchmarks": {
                    b: {
                        "iters": bench_params[b][0],
                        "warmup": bench_params[b][1],
                        "median_ns": round(float(statistics.median(float(statistics.median(r)) for r in rlist)), 1),
                    }
                    for b, rlist in all_raw.items()
                },
            },
        )
        print(f"[baseline] Done in {wall_s:.1f}s -> {_rel_to_repo(outdir)}", flush=True)
    finally:
        if not keep_worktrees:
            cleanup_commit_workdir(adapter.regex_repo_dir, workdir, meta["sha"])
    return 0


def validate_resume_state(args: argparse.Namespace) -> None:
    """Fail fast when resuming Study 3 without its retained DB or per-commit raw directory."""
    db_path = Path(args.db)
    results_dir = Path(args.results_dir)
    checkpoint_path = Path(args.checkpoint)
    progress_log = Path(args.log_dir) / "study3_progress.jsonl"

    explicit_resume = bool(getattr(args, "resume", False)) or args.start_index > 1
    has_partial_state = (
        checkpoint_path.is_file()
        or progress_log.is_file()
        or db_path.is_file()
        or results_dir.is_dir()
    )
    implicit_resume = (not args.force) and has_partial_state
    if not (explicit_resume or implicit_resume):
        return

    missing: List[str] = []
    if not db_path.is_file():
        missing.append(f"--db ({db_path})")
    if not results_dir.is_dir():
        missing.append(f"--results-dir ({results_dir})")
    if not missing:
        return

    missing_desc = ", ".join(missing)
    raise MissingStudy3RawDataError(
        f"Cannot resume Study 3; missing {missing_desc}. "
        "Raw per-iteration samples for Study 3 and the working Study 3 SQLite DB were not retained "
        f"in this repository. Retained per-run medians live in {PORTABLE_STUDY3_DATA} "
        "(run `python regressor.py summary regex --study study3` to summarize offline). "
        "To start a fresh local collection run instead, pass `--force` or specify fresh "
        "`--db`, `--results-dir`, and `--log-dir` paths (new runs regenerate data and will not give identical numbers)."
    )


def run_sweep(args: argparse.Namespace) -> int:
    """Execute the resumable Study 3 commit sweep."""
    if not args.baseline_session or getattr(args, "resume", False):
        validate_resume_state(args)

    regex_repo = Path(args.regex_repo).resolve()
    adapter = RegexAdapter(noise_bench_dir=str(NOISE_BENCH_DIR), regex_repo_dir=str(regex_repo))
    project_toml = REPO_ROOT / "projects" / "regex.toml"
    benches, bench_params, raw_toml = load_benchmark_params(
        adapter,
        project_toml,
        default_iters=args.iters,
        default_warmup=args.warmup,
        iters_config_path=Path(args.iters_config) if args.iters_config else None,
        only_benchmarks=args.benchmark,
    )
    if not benches:
        print("Error: no benchmarks resolved from RegexAdapter.", file=sys.stderr)
        return 1

    if args.baseline_session:
        return run_baseline_session(
            adapter=adapter,
            ref=args.baseline_ref,
            benches=benches,
            bench_params=bench_params,
            reps=args.baseline_reps,
            outdir=Path(args.baseline_dir),
            workdir=Path(args.workdir),
            cpu_id=detect_p_core_cpu(args.p_core)["cpu_id"],
            high_priority=not args.no_high_priority,
            keep_worktrees=args.keep_worktrees,
        )

    commits = load_commit_list(
        Path(args.commits_file),
        Path(args.commits_meta),
        regex_repo,
        explicit_commits=args.commits,
    )
    if args.start_index > 1:
        commits = [c for c in commits if c["index"] >= args.start_index]
    if args.limit is not None:
        commits = commits[: args.limit]
    if not commits:
        print("Error: commit selection is empty.", file=sys.stderr)
        return 1

    topo = detect_p_core_cpu(args.p_core)
    cpu_id = int(topo["cpu_id"])
    pin_check = verify_child_pinning(cpu_id, high_priority=not args.no_high_priority)

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(str(db_path))
    proj_id = db.register_project(
        name=raw_toml["name"],
        repo_url=raw_toml.get("repo_url", ""),
        build_cmd=raw_toml.get("build_cmd", "cargo build --release"),
        adapter=raw_toml["adapter"],
        config_toml=project_toml.read_text(encoding="utf-8"),
    )

    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    progress_log = log_dir / "study3_progress.jsonl"
    canary_log = log_dir / "study3_canary.jsonl"
    checkpoint_path = Path(args.checkpoint)
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    env_meta = {
        "cpu_model": _cpu_model(),
        "nproc": str(os.cpu_count() or "unknown"),
        "rustc_version": _tool_version(["rustc", "--version"]),
        "cargo_version": _tool_version(["cargo", "--version"]),
        "platform": platform.platform(),
        "p_core_topology": topo,
        "pin_verification": pin_check,
    }

    print(
        f"[study3] Starting sweep: {len(commits)} commits x {len(benches)} benchmarks x {args.reps} reps\n"
        f"         DB={_rel_to_repo(db_path)}  workdir={workdir}\n"
        f"         pinning={pin_check}",
        flush=True,
    )

    # Track active sha for graceful SIGINT/SIGTERM cleanup.
    active_sha: List[Optional[str]] = [None]

    def _handle_signal(signum: int, _frame: Any) -> None:
        if active_sha[0] and not args.keep_worktrees:
            cleanup_commit_workdir(regex_repo, workdir, active_sha[0])
        raise KeyboardInterrupt(f"Received signal {signum}")

    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            with contextlib.suppress(OSError, ValueError):
                signal.signal(sig, _handle_signal)

    prev_canary_after: Optional[List[float]] = None
    anchor_canary_before: Optional[List[float]] = None

    completed = 0
    skipped = 0
    failed_builds = 0
    total_t0 = time.monotonic()

    for pos, commit in enumerate(commits, start=1):
        sha = commit["sha"]
        short_sha = commit["short_sha"]
        commit_dir = results_dir / short_sha

        if not args.force and _is_commit_already_complete(db, proj_id, commit_dir, sha, benches, args.reps):
            # Recover previous canary state for continuous drift tracking across restarts.
            existing_meta = json.loads((commit_dir / "meta.json").read_text(encoding="utf-8"))
            c_info = existing_meta.get("canary") or {}
            if anchor_canary_before is None and c_info.get("before_samples_ns"):
                anchor_canary_before = c_info["before_samples_ns"]
            if c_info.get("after_samples_ns"):
                prev_canary_after = c_info["after_samples_ns"]
            skipped += 1
            print(
                f"[{pos}/{len(commits)}] SKIP (complete) {short_sha} ({commit['subject'][:60]})",
                flush=True,
            )
            continue

        # Clean any leftover partial worktree from an interrupted previous attempt.
        cleanup_commit_workdir(regex_repo, workdir, sha)
        active_sha[0] = sha

        _atomic_write_json(
            commit_dir / "meta.json",
            {
                "status": "in_progress",
                "commit_sha": sha,
                "commit_short_sha": short_sha,
                "started_utc": _utc_now_iso(),
            },
        )

        print(f"[{pos}/{len(commits)}] BUILD {short_sha}: {commit['subject']}", flush=True)
        try:
            build_res = adapter.build(sha, workdir=workdir)
            if not build_res.ok:
                now_iso = _utc_now_iso()
                db.insert_commit(
                    project_id=proj_id,
                    sha=sha,
                    short_sha=short_sha,
                    author_date=commit["author_date"],
                    subject=commit["subject"],
                    build_ok=False,
                    build_seconds=build_res.seconds,
                    cpu_model=env_meta["cpu_model"],
                    rustc_version=env_meta["rustc_version"],
                    run_started_utc=now_iso,
                    run_finished_utc=now_iso,
                )
                fail_meta = {
                    "status": "build_failed",
                    "commit_sha": sha,
                    "commit_short_sha": short_sha,
                    "commit_author_date": commit["author_date"],
                    "commit_subject": commit["subject"],
                    "touches_src": commit["touches_src"],
                    "is_doc_or_comment_only": commit["is_doc_or_comment_only"],
                    "is_null_control": commit["is_null_control"],
                    "diff_classification": commit["diff_classification"],
                    "environment": env_meta,
                    "build": {
                        "ok": False,
                        "seconds": build_res.seconds,
                        "log_tail": build_res.log_tail,
                    },
                    "run_started_utc": now_iso,
                    "run_finished_utc": now_iso,
                }
                _atomic_write_json(commit_dir / "meta.json", fail_meta)
                _append_jsonl(
                    progress_log,
                    {
                        "utc": now_iso,
                        "index": commit["index"],
                        "sha": short_sha,
                        "status": "build_failed",
                        "build_seconds": build_res.seconds,
                    },
                )
                failed_builds += 1
                print(f"         BUILD FAILED ({build_res.seconds:.1f}s)", flush=True)
                continue

            # Benchmark + canary timing strictly pinned to one P-core at high priority.
            all_raw: Dict[str, List[List[float]]] = {}
            bench_summaries: Dict[str, Dict[str, Any]] = {}
            with PinnedExecutionContext(cpu_id, high_priority=not args.no_high_priority):
                run_started = _utc_now_iso()
                bench_t0 = time.monotonic()
                canary_before = CanaryBenchmark.run_reps(reps=args.canary_reps, iters=8000, warmup=2)

                for bench in benches:
                    iters, warmup = bench_params[bench]
                    rep_samples: List[List[float]] = []
                    for _ in range(args.reps):
                        samples = adapter.run(
                            bench,
                            iters=iters,
                            warmup=warmup,
                            inject_ns=0,
                            artifact=build_res.artifact,
                        )
                        rep_samples.append(samples)
                    all_raw[bench] = rep_samples

                canary_after = CanaryBenchmark.run_reps(reps=args.canary_reps, iters=8000, warmup=2)
                bench_seconds = round(time.monotonic() - bench_t0, 2)
                run_finished = _utc_now_iso()

            if anchor_canary_before is None:
                anchor_canary_before = canary_before
            canary_info = _summarize_canary(
                canary_before,
                canary_after,
                prev_after=prev_canary_after,
                anchor_before=anchor_canary_before,
            )
            prev_canary_after = canary_after

            # Save compressed raw samples and compute per-rep medians outside timing window.
            db_rows: List[Tuple[int, str, int, str, float]] = []
            commit_id = db.insert_commit(
                project_id=proj_id,
                sha=sha,
                short_sha=short_sha,
                author_date=commit["author_date"],
                subject=commit["subject"],
                build_ok=True,
                build_seconds=build_res.seconds,
                cpu_model=env_meta["cpu_model"],
                rustc_version=env_meta["rustc_version"],
                run_started_utc=run_started,
                run_finished_utc=run_finished,
            )
            for bench in benches:
                rep_samples = all_raw[bench]
                rel_sample_path = _save_raw_samples(commit_dir, bench, rep_samples, args.raw_format)
                rep_medians = [float(statistics.median(r)) for r in rep_samples]
                for rep_idx, med in enumerate(rep_medians, start=1):
                    db_rows.append((commit_id, bench, rep_idx, rel_sample_path, med))

                arr = np.asarray(rep_medians, dtype=np.float64)
                cv_pct = float(np.std(arr, ddof=1) / np.mean(arr) * 100.0) if len(arr) > 1 and np.mean(arr) > 0 else 0.0
                bench_summaries[bench] = {
                    "iters": bench_params[bench][0],
                    "warmup": bench_params[bench][1],
                    "median_ns": round(float(np.median(arr)), 1),
                    "cv_pct": round(cv_pct, 3),
                    "rep_medians_ns": [round(x, 1) for x in rep_medians],
                }
            db.insert_runs_bulk(db_rows)

            meta_payload = {
                "status": "complete",
                "commit_index": commit["index"],
                "commit_sha": sha,
                "commit_short_sha": short_sha,
                "commit_author_date": commit["author_date"],
                "commit_subject": commit["subject"],
                "touches_src": commit["touches_src"],
                "is_doc_or_comment_only": commit["is_doc_or_comment_only"],
                "is_null_control": commit["is_null_control"],
                "diff_classification": commit["diff_classification"],
                "run_started_utc": run_started,
                "run_finished_utc": run_finished,
                "harness_params": {
                    "reps": args.reps,
                    "benches": benches,
                    "bench_params": {b: {"iters": p[0], "warmup": p[1]} for b, p in bench_params.items()},
                    "canary_reps": args.canary_reps,
                },
                "environment": env_meta,
                "build": {
                    "ok": True,
                    "seconds": build_res.seconds,
                    "reused_binary": False,
                },
                "bench_run": {
                    "attempted": True,
                    "ok": True,
                    "seconds": bench_seconds,
                },
                "canary": canary_info,
                "benchmarks": bench_summaries,
            }
            _atomic_write_json(commit_dir / "meta.json", meta_payload)

            within_c = canary_info["within_commit"]
            prev_c = canary_info["vs_prev_commit"]
            _append_jsonl(
                canary_log,
                {
                    "utc": run_finished,
                    "index": commit["index"],
                    "sha": short_sha,
                    "within_status": within_c["status"],
                    "within_shift_pct": within_c["shift_pct"],
                    "before_median_ns": within_c["base_median_ns"],
                    "after_median_ns": within_c["cand_median_ns"],
                    "vs_prev_status": prev_c["status"] if prev_c else "ANCHOR",
                    "vs_prev_shift_pct": prev_c["shift_pct"] if prev_c else 0.0,
                },
            )
            _append_jsonl(
                progress_log,
                {
                    "utc": run_finished,
                    "index": commit["index"],
                    "sha": short_sha,
                    "status": "complete",
                    "build_seconds": build_res.seconds,
                    "bench_seconds": bench_seconds,
                    "canary_within": within_c["status"],
                },
            )
            _atomic_write_json(
                checkpoint_path,
                {
                    "updated_utc": run_finished,
                    "last_completed_index": commit["index"],
                    "last_completed_sha": sha,
                    "completed_in_session": completed + 1,
                    "skipped_already_complete": skipped,
                    "failed_builds": failed_builds,
                    "total_target_commits": len(commits),
                    "db_path": _rel_to_repo(db_path),
                },
            )
            completed += 1
            print(
                f"         OK build={build_res.seconds:.1f}s bench={bench_seconds:.1f}s "
                f"canary={within_c['shift_pct']:+.2f}% ({within_c['status']})",
                flush=True,
            )
        finally:
            active_sha[0] = None
            if not args.keep_worktrees:
                cleanup_commit_workdir(regex_repo, workdir, sha)

    total_wall = round(time.monotonic() - total_t0, 1)
    print(
        f"[study3] Finished in {total_wall}s: completed={completed}, skipped={skipped}, "
        f"failed_builds={failed_builds}",
        flush=True,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser for the Study 3 driver."""
    ap = argparse.ArgumentParser(description="Resumable Study 3 benchmark driver for rust-lang/regex.")
    ap.add_argument("--commits-file", default=str(DEFAULT_COMMITS_FILE), help="Ordered commit SHA file")
    ap.add_argument("--commits-meta", default=str(DEFAULT_COMMITS_META), help="Commit manifest JSON")
    ap.add_argument("--commits", nargs="+", help="Explicit git refs/SHAs (e.g. for 2-commit smoke test)")
    ap.add_argument("--regex-repo", default=str(REPO_ROOT / "regex"), help="Path to local rust-lang/regex clone")
    ap.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite DB path")
    ap.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR), help="Per-commit result directory")
    ap.add_argument("--checkpoint", default=str(DEFAULT_CHECKPOINT_PATH), help="Checkpoint JSON path")
    ap.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR), help="JSONL progress and canary log directory")
    ap.add_argument("--workdir", default=str(DEFAULT_WORKDIR), help="Isolated build worktree directory")
    ap.add_argument("--reps", type=int, default=20, help="Independent process repetitions per commit (default: 20)")
    ap.add_argument("--iters", type=int, default=2000, help="Default timed iterations per rep (default: 2000)")
    ap.add_argument("--warmup", type=int, default=200, help="Default warmup iterations per rep (default: 200)")
    ap.add_argument("--iters-config", help="Optional JSON file mapping benchmark name -> {iters, warmup}")
    ap.add_argument("--canary-reps", type=int, default=15, help="Canary samples before and after each commit")
    ap.add_argument("--benchmark", action="append", help="Restrict run to specific benchmark(s)")
    ap.add_argument("--p-core", type=int, default=None, help="Explicit logical CPU ID to pin timings to")
    ap.add_argument("--no-high-priority", action="store_true", help="Disable HIGH_PRIORITY_CLASS elevation")
    ap.add_argument("--start-index", type=int, default=1, help="1-based commit index to start from")
    ap.add_argument("--limit", type=int, default=None, help="Maximum number of commits to process")
    ap.add_argument(
        "--resume",
        action="store_true",
        help="Resume an existing Study 3 sweep (requires existing --db and --results-dir)",
    )
    ap.add_argument("--force", action="store_true", help="Re-run commits even if checkpoint/DB says complete")
    ap.add_argument("--keep-worktrees", action="store_true", help="Keep isolated worktree + target dirs after run")
    ap.add_argument(
        "--raw-format",
        choices=("gz", "txt", "none"),
        default="gz",
        help="Raw sample archival format per commit (default: gz)",
    )
    ap.add_argument("--baseline-session", action="store_true", help="Collect single-session baseline for evaluate-power")
    ap.add_argument("--baseline-ref", default="3d79fe9", help="Commit ref for baseline session (default: 3d79fe9)")
    ap.add_argument("--baseline-reps", type=int, default=50, help="Reps for single-session baseline (default: 50)")
    ap.add_argument(
        "--baseline-dir",
        default=str(NOISE_BENCH_DIR / "results" / "study3_baseline"),
        help="Output dir for single-session baseline *_rep*.txt files",
    )
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    """Entrypoint for Study 3 benchmark collection."""
    args = build_parser().parse_args(argv)
    try:
        return run_sweep(args)
    except MissingStudy3RawDataError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
