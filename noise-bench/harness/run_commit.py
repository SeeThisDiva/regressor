#!/usr/bin/env python3
"""
Single-commit benchmark harness: checkout -> build -> run N -> store results + meta.json.

Usage:
    python3 harness/run_commit.py <git-ref> [--reps 20] [--iters 2000] [--warmup 200] [--pmu]

Designed to be called once per commit by `run_batch.sh`. Never exits non-zero on
a Rust build failure — it records the failed build in `meta.json` and exits 0 so
long historical commit sweeps do not abort on intermediate unbuildable commits.
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

NOISE_BENCH = Path(os.environ.get("NOISE_BENCH_DIR", Path(__file__).resolve().parent.parent))
REGEX_REPO = Path(os.environ.get("REGEX_REPO", NOISE_BENCH.parent / "regex"))
RESULTS_ROOT = NOISE_BENCH / "results" / "commits"
BENCHES = ["compile_moderate", "find_iter_userid", "is_match_status"]


def sh(cmd, cwd=None, timeout=900):
    """Run a command and return `(returncode, stdout, stderr)`."""
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def cpu_model():
    """Return a human-readable CPU model string for metadata provenance."""
    if platform.system() == "Linux":
        try:
            with open("/proc/cpuinfo", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except FileNotFoundError:
            pass
    return platform.processor() or "unknown"


def get_version(cmd):
    """Return trimmed stdout from a tool `--version` command, or a fallback status."""
    try:
        rc, out, _ = sh(cmd, timeout=30)
        return out.strip() if rc == 0 else "unknown"
    except (FileNotFoundError, OSError):
        return "not installed"


def resolve_commit(ref):
    """Resolve `ref` inside `REGEX_REPO` and return `(sha, author_date, subject)`."""
    if not ref or ref.startswith("-"):
        raise RuntimeError(f"invalid git ref: {ref!r}")
    if not (REGEX_REPO / ".git").exists():
        raise RuntimeError(
            f"regex repository not found at {REGEX_REPO} (clone rust-lang/regex there or set REGEX_REPO)"
        )
    rc, out, err = sh(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=REGEX_REPO)
    if rc != 0:
        raise RuntimeError(f"cannot resolve ref {ref!r}: {err.strip()}")
    sha = out.strip()
    rc, out, err = sh(["git", "show", "-s", "--format=%aI%x00%s", sha, "--"], cwd=REGEX_REPO)
    if rc != 0 or "\x00" not in out:
        raise RuntimeError(f"cannot read metadata for {sha}: {err.strip()}")
    author_date, subject = out.strip().split("\x00", 1)
    return sha, author_date, subject


def checkout(sha):
    """Force-checkout `sha` (detached) and clean untracked build artifacts."""
    rc, _, err = sh(["git", "checkout", "--quiet", "--force", "--detach", sha], cwd=REGEX_REPO)
    if rc != 0:
        raise RuntimeError(f"git checkout {sha} failed: {err.strip()}")
    sh(["git", "clean", "-fdq"], cwd=REGEX_REPO)


def build():
    """Build `noise-bench` in release mode and return `(ok, seconds, log_tail)`."""
    t0 = time.monotonic()
    rc, out, err = sh(["cargo", "build", "--release"], cwd=NOISE_BENCH)
    seconds = time.monotonic() - t0
    # Retain only the last 25 log lines so meta.json stays small across multi-commit sweeps.
    log_tail = (out + err).splitlines()[-25:]
    return rc == 0, seconds, "\n".join(log_tail)


def _parse_perf_stderr(err_text):
    """Parse `perf stat -x,` stderr output into a counter dictionary."""
    metrics = {}
    for line in err_text.splitlines():
        parts = line.strip().split(",")
        if len(parts) >= 3 and parts[0].isdigit():
            metrics[parts[2]] = int(parts[0])
    if "instructions" in metrics and metrics.get("cycles", 0) > 0:
        metrics["ipc"] = round(metrics["instructions"] / metrics["cycles"], 3)
    return metrics


def _split_pmu_csv(out_text):
    """Split `elapsed_ns,tsc_ticks` CSV stdout into separate string line lists."""
    nanos_lines = []
    cycle_lines = []
    for line in out_text.splitlines():
        if line.startswith("elapsed_ns"):
            continue
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(",")
        if len(parts) >= 2:
            nanos_lines.append(parts[0])
            cycle_lines.append(parts[1])
        else:
            nanos_lines.append(stripped)
    return nanos_lines, cycle_lines


def run_bench(bench_name, reps, iters, warmup, outdir, enable_pmu=False):
    """Execute `reps` independent invocations of `bench_name` and store raw outputs."""
    bin_name = "noise-bench.exe" if platform.system() == "Windows" else "noise-bench"
    binpath = NOISE_BENCH / "target" / "release" / bin_name
    if not binpath.exists():
        raise RuntimeError(f"noise-bench binary not found at {binpath}")

    has_perf = False
    if enable_pmu and platform.system() == "Linux":
        rc, _, _ = sh(["perf", "--version"])
        has_perf = rc == 0

    base_cmd = [str(binpath), bench_name, str(iters), str(warmup)]
    if enable_pmu:
        base_cmd.extend(["0", "--pmu"])

    pmu_results = []
    for rep in range(1, reps + 1):
        cmd = (
            ["perf", "stat", "-x,", "-e", "instructions,cycles,cache-misses,branch-misses", *base_cmd]
            if (enable_pmu and has_perf)
            else base_cmd
        )
        rc, out, err = sh(cmd, timeout=300)
        if rc != 0:
            raise RuntimeError(f"{bench_name} rep {rep} failed: {err.strip()}")

        if enable_pmu:
            if has_perf:
                pmu_results.append(_parse_perf_stderr(err))
            nanos_lines, cycle_lines = _split_pmu_csv(out)
            (outdir / f"{bench_name}_rep{rep:03d}.txt").write_text("\n".join(nanos_lines) + "\n", encoding="utf-8")
            if cycle_lines:
                (outdir / f"{bench_name}_cycles_rep{rep:03d}.txt").write_text(
                    "\n".join(cycle_lines) + "\n", encoding="utf-8"
                )
        else:
            (outdir / f"{bench_name}_rep{rep:03d}.txt").write_text(out, encoding="utf-8")

    return pmu_results


def _positive_int(value):
    ival = int(value)
    if ival <= 0:
        raise argparse.ArgumentTypeError(f"must be > 0 (got {value})")
    return ival


def _non_negative_int(value):
    ival = int(value)
    if ival < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0 (got {value})")
    return ival


def main():
    ap = argparse.ArgumentParser(
        description="Build and benchmark a single rust-lang/regex commit using noise-bench."
    )
    ap.add_argument("ref", help="Git ref or SHA in REGEX_REPO to check out and benchmark")
    ap.add_argument("--reps", type=_positive_int, default=20, help="Independent process repetitions (default: 20)")
    ap.add_argument("--iters", type=_positive_int, default=2000, help="Timed iterations per rep (default: 2000)")
    ap.add_argument("--warmup", type=_non_negative_int, default=200, help="Warmup iterations per rep (default: 200)")
    ap.add_argument("--pmu", action="store_true", help="Enable PMU / hardware cycle counters")
    args = ap.parse_args()

    run_started = datetime.now(timezone.utc).isoformat()

    try:
        sha, author_date, subject = resolve_commit(args.ref)
    except RuntimeError as exc:
        print(f"ERROR resolving {args.ref}: {exc}", file=sys.stderr)
        return 1

    short_sha = sha[:10]
    outdir = RESULTS_ROOT / short_sha
    outdir.mkdir(parents=True, exist_ok=True)

    meta = {
        "commit_sha": sha,
        "commit_short_sha": short_sha,
        "commit_author_date": author_date,
        "commit_subject": subject,
        "run_started_utc": run_started,
        "harness_params": {
            "reps": args.reps,
            "iters": args.iters,
            "warmup": args.warmup,
            "benches": BENCHES,
        },
        "environment": {
            "cpu_model": cpu_model(),
            "nproc": str(os.cpu_count() or "unknown"),
            "rustc_version": get_version(["rustc", "--version"]),
            "cargo_version": get_version(["cargo", "--version"]),
            "platform": platform.platform(),
        },
    }

    checkout(sha)
    build_ok, build_seconds, build_log_tail = build()
    meta["build"] = {"ok": build_ok, "seconds": round(build_seconds, 2)}

    if not build_ok:
        meta["build"]["log_tail"] = build_log_tail
        meta["bench_run"] = {"attempted": False, "reason": "build_failed"}
        (outdir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        print(f"BUILD FAILED {short_sha}: {subject!r} ({build_seconds:.1f}s)")
        return 0  # Recordable outcome, not a harness error

    bench_t0 = time.monotonic()
    pmu_telemetry = {}
    try:
        for bench_name in BENCHES:
            bench_pmu = run_bench(
                bench_name, args.reps, args.iters, args.warmup, outdir, enable_pmu=args.pmu
            )
            if bench_pmu:
                pmu_telemetry[bench_name] = bench_pmu
        bench_ok = True
        bench_error = None
    except RuntimeError as exc:
        bench_ok = False
        bench_error = str(exc)
    bench_seconds = time.monotonic() - bench_t0

    meta["bench_run"] = {
        "attempted": True,
        "ok": bench_ok,
        "seconds": round(bench_seconds, 2),
    }
    if pmu_telemetry:
        meta["pmu"] = pmu_telemetry
    if bench_error:
        meta["bench_run"]["error"] = bench_error

    meta["run_finished_utc"] = datetime.now(timezone.utc).isoformat()
    (outdir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    status = "OK" if bench_ok else "BENCH FAILED"
    print(
        f"{status} {short_sha}: {subject!r} "
        f"(build {build_seconds:.1f}s, bench {bench_seconds:.1f}s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
