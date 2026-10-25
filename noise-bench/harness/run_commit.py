#!/usr/bin/env python3
"""
Phase 2 harness: checkout -> build -> run N -> store, with full metadata.

Usage:
    run_commit.py <git-ref> [--reps 20] [--iters 2000] [--warmup 200]

Designed to be called once per commit by an outer driver (phase 4). Never
raises on a build failure -- it records the failure and exits 0, because a
year of someone else's history will include commits that don't build in
isolation (broken intermediate states, MSRV bumps, etc.) and the batch run
must not die on the first one.
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
    """Run a command, return (returncode, stdout, stderr)."""
    p = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
    )
    return p.returncode, p.stdout, p.stderr


def cpu_model():
    if platform.system() == "Linux":
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except FileNotFoundError:
            pass
    return platform.processor() or "unknown"


def get_version(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True)
        return p.stdout.strip() if p.returncode == 0 else "unknown"
    except (FileNotFoundError, OSError):
        return "not installed"


def resolve_commit(ref):
    if not ref or ref.startswith("-"):
        raise RuntimeError(f"invalid git ref: {ref!r}")
    rc, out, err = sh(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=REGEX_REPO)
    if rc != 0:
        raise RuntimeError(f"cannot resolve ref {ref!r}: {err}")
    sha = out.strip()
    rc, out, _ = sh(
        ["git", "show", "-s", "--format=%aI%x00%s", sha, "--"], cwd=REGEX_REPO
    )
    author_date, subject = out.strip().split("\x00", 1)
    return sha, author_date, subject


def checkout(sha):
    # Hard reset any stray state (e.g. Cargo.lock rewrites from a prior
    # build) before moving to the next commit.
    rc, _, err = sh(["git", "checkout", "--quiet", "--force", "--detach", sha], cwd=REGEX_REPO)
    if rc != 0:
        raise RuntimeError(f"git checkout {sha} failed: {err}")
    sh(["git", "clean", "-fdq"], cwd=REGEX_REPO)


def build():
    t0 = time.monotonic()
    rc, out, err = sh(["cargo", "build", "--release"], cwd=NOISE_BENCH)
    seconds = time.monotonic() - t0
    ok = rc == 0
    # Keep only the tail of the log -- full cargo output across 100+ commits
    # is not something anyone will read, and it bloats every meta.json.
    log_tail = (out + err).splitlines()[-25:]
    return ok, seconds, "\n".join(log_tail)


def run_bench(bench_name, reps, iters, warmup, outdir, enable_pmu=False):
    bin_name = "noise-bench.exe" if platform.system() == "Windows" else "noise-bench"
    binpath = NOISE_BENCH / "target" / "release" / bin_name

    has_perf = False
    if enable_pmu and platform.system() == "Linux":
        rc, _, _ = sh(["perf", "--version"])
        has_perf = (rc == 0)

    pmu_results = []
    for rep in range(1, reps + 1):
        if enable_pmu:
            if has_perf:
                cmd = [
                    "perf", "stat", "-x,", "-e",
                    "instructions,cycles,cache-misses,branch-misses",
                    str(binpath), bench_name, str(iters), str(warmup), "0", "--pmu"
                ]
                rc, out, err = sh(cmd, timeout=300)
                metrics = {}
                for line in err.splitlines():
                    parts = line.strip().split(",")
                    if len(parts) >= 3 and parts[0].isdigit():
                        val = int(parts[0])
                        metrics[parts[2]] = val
                if "instructions" in metrics and "cycles" in metrics and metrics["cycles"] > 0:
                    metrics["ipc"] = round(metrics["instructions"] / metrics["cycles"], 3)
                pmu_results.append(metrics)
            else:
                cmd = [str(binpath), bench_name, str(iters), str(warmup), "0", "--pmu"]
                rc, out, err = sh(cmd, timeout=300)

            if rc != 0:
                raise RuntimeError(f"{bench_name} rep {rep} failed: {err}")

            nanos_lines = []
            cycle_lines = []
            for line in out.splitlines():
                if line.startswith("elapsed_ns"):
                    continue
                parts = line.strip().split(",")
                if len(parts) >= 2:
                    nanos_lines.append(parts[0])
                    cycle_lines.append(parts[1])
                elif line.strip():
                    nanos_lines.append(line.strip())

            (outdir / f"{bench_name}_rep{rep:03d}.txt").write_text("\n".join(nanos_lines) + "\n")
            if cycle_lines:
                (outdir / f"{bench_name}_cycles_rep{rep:03d}.txt").write_text("\n".join(cycle_lines) + "\n")
        else:
            rc, out, err = sh(
                [str(binpath), bench_name, str(iters), str(warmup)], timeout=300
            )
            if rc != 0:
                raise RuntimeError(f"{bench_name} rep {rep} failed: {err}")
            (outdir / f"{bench_name}_rep{rep:03d}.txt").write_text(out)

    return pmu_results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ref")
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--iters", type=int, default=2000)
    ap.add_argument("--warmup", type=int, default=200)
    ap.add_argument("--pmu", action="store_true", help="Enable PMU / hardware cycle counters")
    args = ap.parse_args()

    run_started = datetime.now(timezone.utc).isoformat()

    try:
        sha, author_date, subject = resolve_commit(args.ref)
    except RuntimeError as e:
        print(f"ERROR resolving {args.ref}: {e}", file=sys.stderr)
        sys.exit(1)

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
        (outdir / "meta.json").write_text(json.dumps(meta, indent=2))
        print(f"BUILD FAILED {short_sha}: {subject!r} ({build_seconds:.1f}s)")
        sys.exit(0)  # not a harness error -- a real, recordable outcome

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
    except RuntimeError as e:
        bench_ok = False
        bench_error = str(e)
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
    (outdir / "meta.json").write_text(json.dumps(meta, indent=2))

    status = "OK" if bench_ok else "BENCH FAILED"
    print(
        f"{status} {short_sha}: {subject!r} "
        f"(build {build_seconds:.1f}s, bench {bench_seconds:.1f}s)"
    )


if __name__ == "__main__":
    main()
