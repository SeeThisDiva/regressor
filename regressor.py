#!/usr/bin/env python3
"""
regressor: Generalized Continuous Performance Regression Framework
-------------------------------------------------------------------
A decoupled developer platform for cross-language performance benchmarking,
SQLite persistence, non-parametric change-point detection, and live lab-ledger dashboard.
"""

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Dict

import numpy as np

# Ensure root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# UTF-8 stdout configuration for Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from adapters.base import BaseAdapter
from adapters.pymicro_adapter import PyMicroAdapter
from adapters.regex_adapter import RegexAdapter
from core.canary import CanaryBenchmark
from core.db import Database, resolve_commit_prefix
from core.detector import bh_fdr_correct, compare_distributions
from core.interleaved import run_interleaved
from core.models import ProjectConfig
from core.samples import parse_samples
from core.series_detector import detect_series_changepoints_edivisive, rolling_baseline_compare
from core.validation import validate_adapter_synthetic, validate_canary_synthetic

ADAPTER_REGISTRY = {
    "RegexAdapter": RegexAdapter,
    "PyMicroAdapter": PyMicroAdapter,
}

# Session-gap accounting lives in core.session so the API server shares the
# same definition. Re-exported here for backwards compatibility.
from core.session import SESSION_BREAK_MIN, is_session_break, session_gap_minutes  # noqa: E402,F401

_SAFE_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _validate_project_name(project_name: str) -> str:
    """Prevent path traversal when constructing file paths from project names."""
    if not project_name or ".." in project_name or not _SAFE_PROJECT_RE.match(project_name):
        raise ValueError(f"Invalid project name: {project_name!r}")
    return project_name


def load_project_config(project_name: str) -> ProjectConfig:
    _validate_project_name(project_name)
    conf_path = (ROOT_DIR / "projects" / f"{project_name}.toml").resolve()
    if conf_path.parent != (ROOT_DIR / "projects").resolve() or not conf_path.exists():
        raise FileNotFoundError(f"Project config not found: {conf_path}")
    raw = tomllib.loads(conf_path.read_text(encoding="utf-8"))
    return ProjectConfig(
        name=raw["name"],
        repo_url=raw.get("repo_url", ""),
        adapter_name=raw["adapter"],
        build_cmd=raw.get("build_cmd", ""),
        benchmarks=raw.get("benchmarks", []),
        source_paths=raw.get("source_paths", ["src/**"]),
        noise_floor_multiplier=float(raw.get("noise_floor_multiplier", 3.0)),
        canary_threshold_pct=float(raw.get("canary_threshold_pct", 2.5)),
        raw_config=raw,
    )


def _project_benchmarks(db: Database, proj_id: int, name: str):
    """Benchmark list from projects/<name>.toml, else whatever the database holds for the project."""
    try:
        cfg = load_project_config(name)
        if cfg.benchmarks:
            return list(cfg.benchmarks)
    except (FileNotFoundError, ValueError):
        pass
    return db.get_project_benchmarks(proj_id)


def _project_noise_floor_multiplier(name: str) -> float:
    try:
        return load_project_config(name).noise_floor_multiplier
    except (FileNotFoundError, ValueError):
        return 3.0


def _load_triage(name: str) -> Dict[tuple, tuple]:
    """Human triage notes live in projects/<name>.triage.json, not in code:
    [{"benchmark": ..., "commit": <7-char sha>, "status": ..., "note": ...}, ...]"""
    _validate_project_name(name)
    path = (ROOT_DIR / "projects" / f"{name}.triage.json").resolve()
    if path.parent != (ROOT_DIR / "projects").resolve() or not path.exists():
        return {}
    return {(t["benchmark"], t["commit"]): (t["note"], t["status"])
            for t in json.loads(path.read_text(encoding="utf-8"))}


def cmd_export_data(args):
    """Write a project's commits and per-run medians to a portable gzipped JSON file."""
    import gzip
    _validate_project_name(args.project)
    db = Database(args.db)
    proj_id = db.get_project_id(args.project)
    if not proj_id:
        print(f"Error: Project '{args.project}' not found.", file=sys.stderr)
        return 1
    runs = db.get_project_runs(proj_id)
    commits = []
    for c in db.get_project_commits(proj_id):
        commits.append({k: c[k] for k in ("sha", "short_sha", "author_date", "subject", "build_ok", "build_seconds",
                                          "cpu_model", "rustc_version", "run_started_utc", "run_finished_utc")}
                       | {"runs": {b: v for (cid, b), v in runs.items() if cid == c["id"]}})
    out = Path(args.out or ROOT_DIR / "data" / f"{args.project}_history.json.gz")
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump({"format": 1, "project": args.project, "commits": commits}, f, separators=(",", ":"))
    print(f"[regressor] exported {len(commits)} commits, {sum(len(v) for c in commits for v in c['runs'].values())} runs -> {out}")
    return 0


def _validate_import_blob(blob) -> None:
    """Check an export-data file fully before anything is written, so a bad file can't half-import."""
    import math
    if not isinstance(blob, dict) or not isinstance(blob.get("project"), str) or not isinstance(blob.get("commits"), list):
        raise ValueError("not a regressor export file (expected keys 'project' and 'commits')")
    _validate_project_name(blob["project"])
    required = ("sha", "short_sha", "author_date", "subject", "build_ok", "build_seconds",
                "cpu_model", "rustc_version", "run_started_utc", "run_finished_utc", "runs")
    for i, c in enumerate(blob["commits"]):
        if not isinstance(c, dict):
            raise ValueError(f"commit #{i} is not an object")
        missing = [k for k in required if k not in c]
        if missing:
            raise ValueError(f"commit #{i} is missing {missing}")
        if not isinstance(c["sha"], str) or not c["sha"] or not isinstance(c["runs"], dict):
            raise ValueError(f"commit #{i} has an invalid sha or runs field")
        for b, ms in c["runs"].items():
            if not isinstance(ms, list):
                raise ValueError(f"commit {c['sha'][:10]} benchmark {b!r}: runs must be a list")
            for m in ms:
                if isinstance(m, bool) or not isinstance(m, (int, float)) or not math.isfinite(m) or m <= 0:
                    raise ValueError(f"commit {c['sha'][:10]} benchmark {b!r}: invalid median {m!r}")


def cmd_import_data(args):
    """Load a file written by export-data. Idempotent: safe to run repeatedly."""
    import gzip
    try:
        with gzip.open(args.path, "rt", encoding="utf-8") as f:
            blob = json.load(f)
    except (OSError, EOFError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"Error: cannot read {args.path}: {exc}", file=sys.stderr)
        return 1
    try:
        _validate_import_blob(blob)
    except ValueError as exc:
        print(f"Error: {args.path}: {exc}", file=sys.stderr)
        return 1
    db = Database(args.db)
    if not db.get_project_id(blob["project"]):
        cmd_init(argparse.Namespace(db=args.db))
    proj_id = db.get_project_id(blob["project"])
    if not proj_id:
        print(f"Error: no projects/{blob['project']}.toml to register this project against.", file=sys.stderr)
        return 1
    n_runs = 0
    for c in blob["commits"]:
        cid = db.insert_commit(project_id=proj_id, sha=c["sha"], short_sha=c["short_sha"],
                               author_date=c["author_date"], subject=c["subject"], build_ok=bool(c["build_ok"]),
                               build_seconds=c["build_seconds"], cpu_model=c["cpu_model"],
                               rustc_version=c["rustc_version"], run_started_utc=c["run_started_utc"],
                               run_finished_utc=c["run_finished_utc"])
        n_runs += db.insert_runs_bulk((cid, b, i, "", float(m)) for b, ms in c["runs"].items()
                                      for i, m in enumerate(ms, start=1))
    print(f"[regressor] imported {len(blob['commits'])} commits, {n_runs} runs into {blob['project']}")
    return 0


def cmd_dedupe(args):
    """Remove duplicate commits/runs left by pre-checkpoint-2 re-imports."""
    print(Database(args.db).dedupe())
    return 0


def cmd_init(args):
    """Initialize SQLite database and register projects."""
    db = Database(args.db)
    print(f"[regressor] Initialized SQLite database at: {Path(args.db).resolve()}")

    proj_dir = ROOT_DIR / "projects"
    registered = 0
    for toml_file in proj_dir.glob("*.toml"):
        raw = tomllib.loads(toml_file.read_text(encoding="utf-8"))
        p_id = db.register_project(
            name=raw["name"],
            repo_url=raw.get("repo_url", ""),
            build_cmd=raw.get("build_cmd", ""),
            adapter=raw["adapter"],
            config_toml=toml_file.read_text(encoding="utf-8"),
        )
        print(f"  Registered project '{raw['name']}' (ID={p_id}, Adapter={raw['adapter']})")
        registered += 1
    print(f"[regressor] {registered} projects registered successfully.\n")
    return 0


def cmd_validate_adapter(args):
    """Run mandatory 3-point synthetic injection validation test on an adapter."""
    adapter_name = args.adapter
    if adapter_name not in ADAPTER_REGISTRY:
        print(f"Error: Unknown adapter '{adapter_name}'. Available: {list(ADAPTER_REGISTRY.keys())}", file=sys.stderr)
        return 1

    adapter = ADAPTER_REGISTRY[adapter_name]()
    bench = args.benchmark or adapter.list_benchmarks()[0]

    # 1. Adapter validation
    res = validate_adapter_synthetic(adapter, bench, reps=args.reps)

    # 2. Canary validation
    canary_ok = validate_canary_synthetic()

    if res.all_passed and canary_ok:
        print("✅ [Validation Gate Passed] Adapter and canary passed all synthetic ground-truth tests.")
        return 0
    else:
        print("❌ [Validation Gate Failed] Adapter failed synthetic sensitivity requirements. Do not run on real data.", file=sys.stderr)
        return 1


def cmd_import_legacy(args):
    """
    Import existing regex historical commit data from noise-bench/ into SQLite.
    Guarantees persistence and enables verification of refactor fidelity.
    """
    db = Database(args.db)
    p_id = db.get_project_id("regex")
    if not p_id:
        cmd_init(args)
        p_id = db.get_project_id("regex")

    results_dir = ROOT_DIR / "noise-bench" / "results" / "commits"
    commits_file = ROOT_DIR / "noise-bench" / "harness" / "commits.txt"

    if not commits_file.exists():
        print(f"Error: commits.txt not found at {commits_file}", file=sys.stderr)
        return 1

    commits_list = [line.strip() for line in commits_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"\n[regressor] Importing legacy regex historical data ({len(commits_list)} commits)...")

    imported_commits = 0
    imported_runs = 0

    for sha_prefix in commits_list:
        matches = [d for d in results_dir.iterdir() if d.name.startswith(sha_prefix)]
        if not matches:
            continue
        cdir = matches[0]
        meta_file = cdir / "meta.json"
        meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}

        commit_id = db.insert_commit(
            project_id=p_id,
            sha=meta.get("commit_sha", sha_prefix),
            short_sha=sha_prefix,
            author_date=meta.get("commit_author_date", ""),
            subject=meta.get("commit_subject", "unknown"),
            build_ok=meta.get("build", {}).get("ok", True),
            build_seconds=meta.get("build", {}).get("seconds", 0.0),
            cpu_model=meta.get("environment", {}).get("cpu_model", "unknown"),
            rustc_version=meta.get("environment", {}).get("rustc_version", "unknown"),
            run_started_utc=meta.get("run_started_utc", ""),
            run_finished_utc=meta.get("run_finished_utc", ""),
        )
        imported_commits += 1

        # Import benchmark runs (one transaction per commit; re-running is a no-op)
        for bench in _project_benchmarks(db, p_id, "regex"):
            rows = []
            for idx, rf in enumerate(sorted(cdir.glob(f"{bench}_rep*.txt")), start=1):
                rows.append((commit_id, bench, idx, str(rf),
                             float(np.median(parse_samples(rf.read_text(), source=str(rf))))))
            imported_runs += db.insert_runs_bulk(rows)

    print(f"  Imported {imported_commits} commits and {imported_runs} benchmark runs into SQLite.")
    return 0


def cmd_batch(args):
    """
    Run batch change-point detection across all adjacent commits in SQLite.
    Applies Benjamini-Hochberg FDR correction across the entire batch.
    With --verify-legacy, asserts exact reproduction of the original regex study (REPORT.md:
    27 commits, 78 comparisons, 5 flags); that check is a property of one dataset, not of batch.
    """
    db = Database(args.db)
    proj_id = db.get_project_id(args.project)
    if not proj_id:
        print(f"Error: Project '{args.project}' not found in database. Run 'regressor init' first.", file=sys.stderr)
        return 1

    commits = db.get_project_commits(proj_id)
    if len(commits) < 2:
        print(f"Error: Need at least 2 commits to run batch analysis. Found {len(commits)}.", file=sys.stderr)
        return 1

    db.clear_project_comparisons(proj_id)

    benches = _project_benchmarks(db, proj_id, args.project)
    nf_mult = _project_noise_floor_multiplier(args.project)
    window_k = getattr(args, "rolling_window", 1) or 1
    adjust_autocorr = bool(getattr(args, "adjust_autocorr", False))
    fdr_method = getattr(args, "fdr", "bh") or "bh"
    runs_by = db.get_project_runs(proj_id)          # one query instead of one per (commit, benchmark)
    comparisons = []

    triage_notes = _load_triage(args.project)   # projects/<name>.triage.json

    for i in range(1, len(commits)):
        base_commit = commits[i - 1]
        cand_commit = commits[i]
        gap_min = session_gap_minutes(base_commit, cand_commit)

        for bench in benches:
            base_runs = runs_by.get((base_commit["id"], bench), [])
            cand_runs = runs_by.get((cand_commit["id"], bench), [])

            if len(base_runs) < 5 or len(cand_runs) < 5:
                continue

            if window_k > 1:
                hist_runs = [runs_by.get((commits[j]["id"], bench), [])
                             for j in range(max(0, i - window_k), i)]
                hist_runs = [r for r in hist_runs if len(r) >= 5]
                res = rolling_baseline_compare(
                    hist_runs,
                    cand_runs,
                    window_k=window_k,
                    alpha=0.01,
                    noise_floor_multiplier=nf_mult,
                    adjust_autocorr=adjust_autocorr,
                )
            else:
                res = compare_distributions(
                    np.array(base_runs, dtype=np.float64),
                    np.array(cand_runs, dtype=np.float64),
                    alpha=0.01,
                    noise_floor_multiplier=nf_mult,
                    adjust_autocorr=adjust_autocorr,
                )

            res.update({
                "base_commit_id": base_commit["id"],
                "cand_commit_id": cand_commit["id"],
                "base_sha": base_commit["short_sha"],
                "cand_sha": cand_commit["short_sha"],
                "cand_subject": cand_commit["subject"],
                "benchmark": bench,
                "session_gap_min": gap_min,
            })
            comparisons.append(res)

    # FDR correction across the full batch (BH by default; --fdr by for arbitrary dependence)
    bh_fdr_correct(comparisons, alpha=0.05, method=fdr_method)

    # Persist comparisons to SQLite
    n_flags = 0
    n_flags_fdr = 0

    for c in comparisons:
        key = (c["benchmark"], c["cand_sha"][:7])
        note, status = triage_notes.get(key, ("", "unreviewed"))
        if c["verdict"] == "flag":
            n_flags += 1
            if c["fdr_significant"]:
                n_flags_fdr += 1

        db.insert_comparison(
            project_id=proj_id,
            base_commit_id=c["base_commit_id"],
            cand_commit_id=c["cand_commit_id"],
            benchmark=c["benchmark"],
            p_value=c["p_value"],
            shift_pct=c["shift_pct"],
            noise_floor_pct=c["noise_floor_pct"],
            verdict=c["verdict"],
            fdr_significant=c["fdr_significant"],
            resolution_note=note,
            resolution_status=status,
            canary_status="NOT_RECORDED",  # legacy runs had no canary
            pmu_status="UNAVAILABLE",       # no hardware counters were ever read
            session_gap_min=c["session_gap_min"],
        )

    print(f"\n{'='*75}")
    print(f"  regressor Batch Analysis — Project: '{args.project}'")
    print(f"{'='*75}")
    print(f"  Total Commits Analyzed:    {len(commits)}")
    print(f"  Total Pairwise Tests:      {len(comparisons)}")
    print(f"  Flagged Pre-FDR:           {n_flags}")
    fdr_label = "" if fdr_method == "bh" else "BY, "
    print(f"  Flagged Post-FDR ({fdr_label}α=0.05): {n_flags_fdr}")
    print(f"{'='*75}\n")

    for c in comparisons:
        if c["verdict"] == "flag" and c["fdr_significant"]:
            gap = c["session_gap_min"]
            gap_tag = f"  [SESSION_BREAK: {gap:.0f} min gap before run — environment-confounded]" \
                if is_session_break(gap) else ""
            print(f"  [FLAG] {c['benchmark']:20s} {c['base_sha']} -> {c['cand_sha']}  Shift: {c['shift_pct']:+.2f}%  p={c['p_value']:.2e}  floor={c['noise_floor_pct']:.2f}%{gap_tag}")
            print(f"         {c['cand_subject']}\n")

    # Reproduction check against the original study (REPORT.md). The flag set
    # must match; noise floors are ~2.6% higher than the original because this
    # code uses sample std (ddof=1) instead of population std: ratio sqrt(20/19).
    if args.verify_legacy:
        if fdr_method != "bh":
            print("Error: --verify-legacy reproduces the original BH-corrected study; drop --fdr by.", file=sys.stderr)
            return 1
        # Explicit checks, not `assert`: asserts vanish under `python -O`.
        expected = {"commits": (len(commits), 27), "comparisons": (len(comparisons), 78),
                    "flags": (n_flags, 5), "FDR flags": (n_flags_fdr, 5)}
        bad = [f"{k}: expected {e}, got {g}" for k, (g, e) in expected.items() if g != e]
        if bad:
            print("Error: legacy reproduction mismatch: " + "; ".join(bad), file=sys.stderr)
            return 1
        print("✅ Same flag set as REPORT.md (27 commits, 78 comparisons, 5 flags). "
              "Noise floors differ by sqrt(20/19) because of ddof=1.\n")

    return 0


def cmd_analyze(args):
    """Ad-hoc compare any two commits."""
    db = Database(args.db)
    proj_id = db.get_project_id(args.project)
    if not proj_id:
        print(f"Error: Project '{args.project}' not found.", file=sys.stderr)
        return 1

    commits = db.get_project_commits(proj_id)
    base_c, err_b = resolve_commit_prefix(commits, args.base_sha)
    cand_c, err_c = resolve_commit_prefix(commits, args.cand_sha)
    if err_b or err_c:
        print(f"Error: {err_b or err_c}", file=sys.stderr)
        return 1
    if base_c["id"] == cand_c["id"]:
        print("Error: base and candidate resolve to the same commit.", file=sys.stderr)
        return 1
    benches = _project_benchmarks(db, proj_id, args.project)

    print(f"\n[Ad-Hoc Comparison] {base_c['short_sha']} -> {cand_c['short_sha']}")
    for bench in benches:
        b_runs = db.get_commit_runs(base_c["id"], bench)
        c_runs = db.get_commit_runs(cand_c["id"], bench)
        if b_runs and c_runs:
            res = compare_distributions(np.array(b_runs), np.array(c_runs))
            tag = "[FLAG]" if res["verdict"] == "flag" else "[PASS]"
            print(f"  {tag:6s} {bench:20s} Shift: {res['shift_pct']:+.2f}%  p={res['p_value']:.2e}  floor={res['noise_floor_pct']:.2f}%")
    print()
    return 0


def positive_int(s: str) -> int:
    """argparse type: integer >= 1."""
    try:
        v = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected an integer, got {s!r}") from None
    if v < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {v}")
    return v


def non_negative_int(s: str) -> int:
    """argparse type: integer >= 0."""
    try:
        v = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected an integer, got {s!r}") from None
    if v < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {v}")
    return v


def non_negative_float(s: str) -> float:
    """argparse type: finite float >= 0."""
    try:
        v = float(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a number, got {s!r}") from None
    if not (v >= 0.0 and v != float("inf")):
        raise argparse.ArgumentTypeError(f"must be a finite number >= 0, got {s}")
    return v


def probability(s: str) -> float:
    """argparse type: significance level strictly between 0 and 1."""
    try:
        v = float(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a number, got {s!r}") from None
    if not (0.0 < v < 1.0):
        raise argparse.ArgumentTypeError(f"must be between 0 and 1 (exclusive), got {s}")
    return v


def _make_adapter(name: str, args) -> "BaseAdapter":
    if name == "RegexAdapter":
        return RegexAdapter(regex_repo_dir=getattr(args, "repo", None))
    if name == "PyMicroAdapter":
        return PyMicroAdapter()
    raise SystemExit(f"Unknown adapter '{name}'. Available: {list(ADAPTER_REGISTRY)}")


def _env_info() -> Dict[str, str]:
    import platform
    cpu = platform.processor() or "unknown"
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    return {"platform": platform.platform(), "cpu": cpu}


def cmd_compare_interleaved(args):
    """Build two commits and benchmark them in alternation (paired Wilcoxon)."""
    adapter = _make_adapter(args.adapter, args)
    benches = args.benchmark or adapter.list_benchmarks()
    workdir = Path(args.workdir)

    builds = {}
    for label, ref in (("base", args.base), ("cand", args.cand)):
        print(f"[build] {label} = {ref} ...", flush=True)
        br = adapter.build(ref, workdir=workdir)
        if not br.ok:
            print(f"Error: build failed for {ref}:\n{br.log_tail}", file=sys.stderr)
            return 2
        builds[label] = br.artifact
        print(f"        ok ({br.seconds}s) -> {br.artifact}")

    # Invariant canary, sampled before and after the interleaved window. Interleaving cancels
    # slow drift, but a host migration or throttling event mid-window still deserves a warning.
    canary_pre = CanaryBenchmark.run_reps(reps=args.canary_reps) if args.canary_reps > 0 else None

    results = []
    req_ci = bool(getattr(args, "require_ci_bound", False))
    for i, bench in enumerate(benches):
        print(f"[run] {bench}: {args.pairs} interleaved pairs ...", flush=True)
        r = run_interleaved(adapter, bench, builds["base"], builds["cand"], pairs=args.pairs,
                            iters=args.iters, warmup=args.warmup, inject_ns_b=args.inject_ns,
                            alpha=args.alpha, min_effect_pct=args.min_effect, seed=args.seed + i,
                            require_ci_bound=req_ci)
        results.append(r)

    canary = None
    if canary_pre is not None:
        canary_post = CanaryBenchmark.run_reps(reps=args.canary_reps)
        canary = CanaryBenchmark.evaluate_drift(canary_pre, canary_post)
        print(f"[canary] shift={canary['shift_pct']:+.2f}% -> {canary['status']}")

    # Multiple benchmarks -> control FDR across them.
    bh_fdr_correct(results, alpha=args.alpha)
    for r in results:
        r["final_verdict"] = "flag" if (r["verdict"] == "flag" and r["fdr_significant"]) else "ok"
        r["canary_status"] = canary["status"] if canary else "NOT_RECORDED"
        if r["final_verdict"] == "flag" and canary and canary["is_drifted"]:
            r["attribution"] = "ENVIRONMENT_DRIFT_SUSPECTED"

    print()
    for r in results:
        tag = "FLAG" if r["final_verdict"] == "flag" else " ok "
        lo, hi = r["shift_ci95_pct"]
        print(f"  [{tag}] {r['benchmark']:20s} shift={r['shift_pct']:+.2f}% CI95=[{lo:+.2f}, {hi:+.2f}]  "
              f"p={r['p_value']:.2e}{' (floor: all pairs same sign)' if r.get('p_at_floor') else ''}  "
              f"order-effect={r['order_effect_pct']}%")
    print()

    env = _env_info()
    if args.json:
        Path(args.json).write_text(json.dumps({"base": args.base, "cand": args.cand, "env": env,
                                               "canary": canary, "results": results}, indent=2), encoding="utf-8")
    if args.markdown:
        from core.report import render_markdown
        Path(args.markdown).write_text(render_markdown(args.base, args.cand, results, env, canary), encoding="utf-8")

    regressed = any(r["final_verdict"] == "flag" and r["shift_pct"] > 0 for r in results)
    env_suspect = bool(canary and canary["is_drifted"])
    if regressed and args.fail_on_regression and env_suspect and getattr(args, "no_fail_on_env_suspect", False):
        print("[canary] host drift suspected: flagged slowdown reported but not failing (--no-fail-on-env-suspect)")
        return 0
    return 1 if (regressed and args.fail_on_regression) else 0


def cmd_evaluate_power(args):
    """False-positive rate three ways + power curve, all from real recorded runs."""
    from core.power import aa_contiguous_split, aa_random_split, evaluate_power_curve, load_session_medians, null_transition_fpr
    _db = Database(args.db)
    _pid = _db.get_project_id(args.project)
    benches = _project_benchmarks(_db, _pid, args.project) if _pid else ["compile_moderate", "find_iter_userid", "is_match_status"]
    session = load_session_medians(Path(args.session_dir), benches)
    if not session:
        print(f"Error: no session data in {args.session_dir}", file=sys.stderr)
        return 1

    bar = "=" * 78
    print(f"\n{bar}\n  False-positive rate, measured three ways (alpha=0.01, 3x CV floor)\n{bar}")
    print(f"  Session data: {args.session_dir} ({', '.join(f'{b}: {len(v)} runs' for b, v in session.items())})\n")

    print("  1) Within-session A/A, random split (jitter only)")
    for b, meds in session.items():
        r = aa_random_split(meds, trials=args.trials)
        print(f"     {b:18s} {r['flags']:4d}/{r['trials']} = {r['fpr_pct']:5.2f}%   95% CI {r['ci95_pct']}")

    print("\n  2) Within-session A/A, first half vs second half (adds slow in-session drift)")
    for b, meds in session.items():
        r = aa_contiguous_split(meds)
        print(f"     {b:18s} verdict={r['verdict']:4s} shift={r['shift_pct']:+.2f}%  p={r['p_value']:.2e}  floor={r['noise_floor_pct']:.2f}%")

    db = Database(args.db)
    proj_id = db.get_project_id(args.project)
    rows = [dict(r) for r in db.get_project_comparisons(proj_id)] if proj_id else []
    print("\n  3) Real null transitions: adjacent commits whose candidate is doc-only")
    print("     (classified by commit subject 'doc:'/'docs:'; same compiled code, separate runs)")
    if not rows or rows[0].get("session_gap_min") is None:
        print("     No comparisons with session gaps in DB. Run `regressor batch` first.")
    else:
        n = null_transition_fpr(rows)
        for label, key in (("all", "all"), ("within session (gap <= 15 min)", "within_session"),
                           ("across a session break", "across_session_break")):
            s = n[key]
            print(f"     {label:32s} {s['flags']:2d}/{s['n']:2d} = {s['fpr_pct']:5.2f}%   95% CI {s['ci95_pct']}")
        print(f"     doc-only commits: {', '.join(n['null_commits'])}")
        for f in n["flagged"]:
            print(f"       flagged: {f['cand_sha']} {f['benchmark']} {f['shift_pct']:+.2f}% (gap {f['session_gap_min']} min)")

    bench = args.benchmark or next(iter(session))
    if bench not in session:
        print(f"Error: benchmark '{bench}' not in session data ({', '.join(session)})", file=sys.stderr)
        return 1
    pw = evaluate_power_curve(session[bench], trials_per_point=args.power_trials)
    print(f"\n{bar}\n  Power (within-session noise only): {bench}, pool={pw['pool_size']} runs, "
          f"{pw['trials_per_point']} trials/point\n{bar}")
    effs = list(next(iter(pw["power_grid"].values())).keys())
    print("  " + "N".ljust(6) + "".join(f"{e:>8s}" for e in effs) + "   MDE@80%")
    for k, g in pw["power_grid"].items():
        mde = pw["mde_at_80_pct_power"][k]
        print("  " + k.ljust(6) + "".join(f"{v:8.2f}" for v in g.values()) + f"   {('+%g%%' % mde) if mde else '> max'}")
    print()
    return 0


def cmd_changepoint(args):
    """Run series-level E-Divisive change-point detection across the commit time series."""
    db = Database(args.db)
    proj_id = db.get_project_id(args.project)
    if not proj_id:
        print(f"Error: Project '{args.project}' not found.", file=sys.stderr)
        return 1

    commits = db.get_project_commits(proj_id)
    if len(commits) < 6:
        print("Error: Need at least 6 commits for series change-point detection.", file=sys.stderr)
        return 1

    bench = args.benchmark or _project_benchmarks(db, proj_id, args.project)[0]
    known = db.get_project_benchmarks(proj_id)
    if bench not in known:
        print(f"Error: benchmark '{bench}' has no runs in '{args.project}' (have: {', '.join(known)})", file=sys.stderr)
        return 1
    shas = [c["short_sha"] for c in commits]
    series_runs = [db.get_commit_runs(c["id"], bench) for c in commits]

    print(f"\n{'='*75}")
    print("  regressor Series-Level E-Divisive Change-Point Detection")
    print(f"  Project: '{args.project}' | Benchmark: '{bench}' | Commits: {len(commits)}")
    print(f"{'='*75}\n")

    known_breaks = [i for i in range(1, len(commits))
                    if is_session_break(session_gap_minutes(commits[i - 1], commits[i]))]
    nf_mult = _project_noise_floor_multiplier(args.project)
    cps = detect_series_changepoints_edivisive(shas, series_runs, significance_alpha=args.alpha,
                                               known_breaks=known_breaks, noise_floor_multiplier=nf_mult)
    if not cps:
        print("  No statistically significant structural change points detected across the series.\n")
        return 0

    print(f"  Found {len(cps)} structural change point(s):\n")
    for cp in cps:
        print(f"  -> Change-Point at Commit: {cp['commit_sha']} (Index: {cp['index']})")
        print(f"     Left Segment:  {cp['left_range']} (Median: {cp['left_median_ns']:,} ns)")
        print(f"     Right Segment: {cp['right_range']} (Median: {cp['right_median_ns']:,} ns)")
        tags = []
        if cp["session_break"]:
            tags.append("SESSION_BREAK: environment-confounded")
        if not cp["exceeds_noise_floor"]:
            tags.append(f"below {cp['noise_floor_pct']:.2f}% noise floor")
        tag = f"   [{'; '.join(tags)}]" if tags else ""
        print(f"     Shift:         {cp['shift_pct']:+.2f}%{tag}")
        print(f"     Energy Stat:   {cp['energy_stat']:.1f} (Permutation p={cp['permutation_p_value']:.4f})\n")
    print("  Note: a change point says the level moved, not why. Host drift and code")
    print("  changes look the same here; re-measure with compare-interleaved.\n")
    print(f"{'='*75}\n")
    return 0


def cmd_bisect(args):
    """Build-based bisection: each probe is an interleaved A/B run against the good build."""
    from core.bisect import bisect_builds, git_rev_list
    if args.demo:
        # Simulated history: 16 fake commits; c09 adds 400 ns of real busy-wait per
        # iteration and every later commit keeps it. Timings are real measurements.
        commits = [f"c{i:02d}" for i in range(16)]
        adapter = PyMicroAdapter({c: (400 if i >= 9 else 0) for i, c in enumerate(commits)})
        bench = args.benchmark or "json_loads"
        print("[demo] simulated 16-commit history, true culprit = c09 (+400 ns/iter busy-wait)")
    else:
        if not (args.repo and args.good and args.bad):
            print("Error: --repo, --good and --bad are required (or use --demo)", file=sys.stderr)
            return 1
        adapter = _make_adapter(args.adapter, args)
        commits = git_rev_list(Path(args.repo), args.good, args.bad)
        bench = args.benchmark or adapter.list_benchmarks()[0]
    print(f"[bisect] {len(commits)} commits, benchmark={bench}, {args.pairs} pairs per probe")
    res = bisect_builds(adapter, commits, bench, pairs=args.pairs, iters=args.iters, warmup=args.warmup,
                        workdir=Path(args.workdir), alpha=args.alpha, min_effect_pct=args.min_effect)
    if not res["reproduced"]:
        print("\n  Bad commit does not regress against good under interleaved A/B. Nothing to bisect.\n")
        return 0
    print(f"\n  first bad: {res['culprit']}   last good: {res['last_good']}   "
          f"builds: {res['builds']} (vs {len(commits)} for a linear scan)\n")
    return 0


def cmd_serve(args):
    """Launch FastAPI backend and live lab-ledger dashboard."""
    import uvicorn

    from server.app import create_app

    app = create_app(db_path=args.db)
    print(f"\n[regressor] Serving live performance ledger at: http://localhost:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="regressor",
        description="Performance regression detection for noisy machines",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", default="regressor.db", help="Path to SQLite database file")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    adapters = list(ADAPTER_REGISTRY)

    subparsers.add_parser("init", help="Initialize SQLite database and load projects")

    p_val = subparsers.add_parser("validate-adapter", help="3-point injection test on an adapter")
    p_val.add_argument("adapter", choices=adapters)
    p_val.add_argument("--benchmark")
    p_val.add_argument("--reps", type=int, default=25)

    subparsers.add_parser("import-legacy", help="Import legacy regex benchmark data into SQLite")
    p_exp = subparsers.add_parser("export-data", help="Write a project's commits and run medians to portable JSON")
    p_exp.add_argument("project")
    p_exp.add_argument("--out")
    p_imp = subparsers.add_parser("import-data", help="Load a file written by export-data (idempotent)")
    p_imp.add_argument("path")
    subparsers.add_parser("dedupe", help="Remove duplicate commits/runs from an older database")

    p_batch = subparsers.add_parser("batch", help="Adjacent-pair detection across stored commits (+BH-FDR)")
    p_batch.add_argument("project", default="regex", nargs="?")
    p_batch.add_argument("--rolling-window", type=positive_int, default=1,
                         help="Rolling baseline window K in prior commits (default 1 = adjacent pair)")
    p_batch.add_argument("--adjust-autocorr", action="store_true",
                         help="Compute moving-block bootstrap p-values alongside Mann-Whitney (partial adjustment under autocorrelation)")
    p_batch.add_argument("--fdr", choices=("bh", "by"), default="bh",
                         help="FDR method: bh = Benjamini-Hochberg (default, original study); "
                              "by = Benjamini-Yekutieli, valid under the negative dependence of adjacent comparisons")
    p_batch.add_argument("--verify-legacy", action="store_true",
                         help="Assert the original regex study numbers (27 commits, 78 comparisons, 5 flags)")

    p_ana = subparsers.add_parser("analyze", help="Compare two stored commits")
    p_ana.add_argument("project")
    p_ana.add_argument("base_sha")
    p_ana.add_argument("cand_sha")

    def add_run_opts(p, default_pairs):
        p.add_argument("--adapter", choices=adapters, default="RegexAdapter")
        p.add_argument("--repo", help="Path to the project clone (RegexAdapter)")
        p.add_argument("--workdir", default=".regressor-builds", help="Where isolated builds go")
        p.add_argument("--pairs", type=positive_int, default=default_pairs)
        p.add_argument("--iters", type=positive_int, default=2000)
        p.add_argument("--warmup", type=non_negative_int, default=200)
        p.add_argument("--alpha", type=probability, default=0.01)
        p.add_argument("--min-effect", type=non_negative_float, default=1.0, help="Practical threshold, percent")

    p_intl = subparsers.add_parser("compare-interleaved", help="Build two commits, run them in alternation")
    add_run_opts(p_intl, 20)
    p_intl.add_argument("--base", required=True, help="Base ref (PyMicroAdapter: any label)")
    p_intl.add_argument("--cand", required=True, help="Candidate ref")
    p_intl.add_argument("--benchmark", action="append", help="Repeatable; default = all")
    p_intl.add_argument("--inject-ns", type=non_negative_int, default=0, help="Ground-truth busy-wait added to candidate")
    p_intl.add_argument("--seed", type=int, default=0)
    p_intl.add_argument("--canary-reps", type=non_negative_int, default=10,
                        help="Canary samples before and after the run (0 disables)")
    p_intl.add_argument("--require-ci-bound", action="store_true",
                        help="Require the 95%% bootstrap CI bound (not just point estimate) to clear --min-effect")
    p_intl.add_argument("--json")
    p_intl.add_argument("--markdown")
    p_intl.add_argument("--fail-on-regression", action="store_true",
                        help="Exit 1 on a flagged slowdown. By default this also fails when the canary reports "
                             "ENVIRONMENT_SUSPECT (the flag is still reported, attributed to drift)")
    p_intl.add_argument("--no-fail-on-env-suspect", action="store_true",
                        help="With --fail-on-regression: do not fail when the canary says the host drifted")

    p_pwr = subparsers.add_parser("evaluate-power", help="False-positive rate three ways + power curve")
    p_pwr.add_argument("project", default="regex", nargs="?")
    p_pwr.add_argument("--benchmark")
    p_pwr.add_argument("--session-dir", default=str(ROOT_DIR / "noise-bench" / "results" / "20260813T150528_baseline"))
    p_pwr.add_argument("--trials", type=positive_int, default=1000)
    p_pwr.add_argument("--power-trials", type=positive_int, default=300)

    p_cp = subparsers.add_parser("changepoint", help="Series-level E-Divisive change-point detection")
    p_cp.add_argument("project", default="regex", nargs="?")
    p_cp.add_argument("--benchmark")
    p_cp.add_argument("--alpha", type=probability, default=0.05)

    p_bis = subparsers.add_parser("bisect", help="Build-based bisection with interleaved probes")
    add_run_opts(p_bis, 12)
    p_bis.add_argument("--good")
    p_bis.add_argument("--bad")
    p_bis.add_argument("--benchmark")
    p_bis.add_argument("--demo", action="store_true", help="Simulated history with PyMicroAdapter")

    p_srv = subparsers.add_parser("serve", help="Launch FastAPI server and dashboard")
    p_srv.add_argument("--port", type=positive_int, default=8000)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 0

    commands = {
        "init": cmd_init,
        "validate-adapter": cmd_validate_adapter,
        "import-legacy": cmd_import_legacy,
        "export-data": cmd_export_data,
        "import-data": cmd_import_data,
        "dedupe": cmd_dedupe,
        "batch": cmd_batch,
        "analyze": cmd_analyze,
        "compare-interleaved": cmd_compare_interleaved,
        "evaluate-power": cmd_evaluate_power,
        "changepoint": cmd_changepoint,
        "bisect": cmd_bisect,
        "serve": cmd_serve,
    }
    # User-facing errors (bad project name, underpowered pair count, unknown benchmark, missing
    # file...) become one clean line and exit 1. Anything else is a bug: let it raise.
    try:
        return commands[args.command](args)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
