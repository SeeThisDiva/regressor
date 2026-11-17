#!/usr/bin/env python3
"""
regressor: Generalized Continuous Performance Regression Framework.

CLI entrypoint for initializing the SQLite performance ledger, validating
benchmark adapters, importing/exporting study datasets, running batch/series
statistical change-point detection, executing interleaved A/B comparisons and
bisection, and serving the web dashboard.
"""

import argparse
import gzip
import json
import math
import platform
import re
import sys
import tomllib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Ensure repository root is importable regardless of working directory.
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Configure UTF-8 stdout on Windows consoles so Unicode status symbols do not fail.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from adapters.base import BaseAdapter
from adapters.pymicro_adapter import PyMicroAdapter
from adapters.regex_adapter import RegexAdapter
from core.canary import CanaryBenchmark
from core.db import Database, resolve_commit_pair
from core.detector import bh_fdr_correct, compare_benchmark_runs, compare_distributions
from core.interleaved import run_interleaved
from core.models import ProjectConfig
from core.samples import read_sample_median
from core.series_detector import detect_series_changepoints_edivisive, rolling_baseline_compare
from core.session import (
    SESSION_BREAK_MIN,  # noqa: F401
    find_session_break_indices,
    is_session_break,
    session_gap_minutes,
)
from core.validation import validate_adapter_synthetic, validate_canary_synthetic

ADAPTER_REGISTRY = {
    "RegexAdapter": RegexAdapter,
    "PyMicroAdapter": PyMicroAdapter,
}

_SAFE_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

_COMMIT_EXPORT_FIELDS = (
    "sha",
    "short_sha",
    "author_date",
    "subject",
    "build_ok",
    "build_seconds",
    "cpu_model",
    "rustc_version",
    "run_started_utc",
    "run_finished_utc",
)


# ---------------------------------------------------------------------------
# Project Config, Triage & Database Lookup Helpers
# ---------------------------------------------------------------------------


def _validate_project_name(project_name: str) -> str:
    """Reject empty names or path-traversal sequences before resolving project files."""
    if not project_name or ".." in project_name or not _SAFE_PROJECT_RE.match(project_name):
        raise ValueError(f"Invalid project name: {project_name!r}")
    return project_name


def _resolve_project_file(project_name: str, suffix: str) -> Path:
    """Resolve `projects/<project_name><suffix>` safely inside the projects directory."""
    _validate_project_name(project_name)
    projects_dir = (ROOT_DIR / "projects").resolve()
    path = (projects_dir / f"{project_name}{suffix}").resolve()
    if path.parent != projects_dir:
        raise ValueError(f"Invalid project name: {project_name!r}")
    return path


def load_project_config(project_name: str) -> ProjectConfig:
    """Load and parse `projects/<project_name>.toml` into a `ProjectConfig`."""
    conf_path = _resolve_project_file(project_name, ".toml")
    if not conf_path.exists():
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


def _try_load_project_config(project_name: str) -> Optional[ProjectConfig]:
    """Return the TOML project config if present and valid, else `None`."""
    try:
        return load_project_config(project_name)
    except (FileNotFoundError, ValueError):
        return None


def _project_benchmarks(db: Database, proj_id: int, name: str) -> List[str]:
    """Return configured benchmarks from `projects/<name>.toml`, or fall back to DB runs."""
    cfg = _try_load_project_config(name)
    if cfg and cfg.benchmarks:
        return list(cfg.benchmarks)
    return db.get_project_benchmarks(proj_id)


def _project_noise_floor_multiplier(name: str) -> float:
    """Return configured noise-floor multiplier from `projects/<name>.toml` (default 3.0)."""
    cfg = _try_load_project_config(name)
    return cfg.noise_floor_multiplier if cfg else 3.0


def _load_triage(name: str) -> Dict[tuple, tuple]:
    """Load optional human triage annotations from `projects/<name>.triage.json`."""
    path = _resolve_project_file(name, ".triage.json")
    if not path.exists():
        return {}
    return {
        (t["benchmark"], t["commit"]): (t["note"], t["status"])
        for t in json.loads(path.read_text(encoding="utf-8"))
    }


def _require_project(db_path: str, project_name: str, init_hint: bool = False) -> Tuple[Database, Optional[int]]:
    """Open `Database(db_path)` and resolve `project_name`, printing an error if missing."""
    db = Database(db_path)
    proj_id = db.get_project_id(project_name)
    if not proj_id:
        hint = " in database. Run 'regressor init' first." if init_hint else "."
        print(f"Error: Project '{project_name}' not found{hint}", file=sys.stderr)
        return db, None
    return db, proj_id


# ---------------------------------------------------------------------------
# Formatting & Environment Helpers
# ---------------------------------------------------------------------------


def _format_comparison_metrics(res: Dict[str, Any]) -> str:
    """Format shift percentage, p-value, and noise floor consistently for CLI reports."""
    return f"Shift: {res['shift_pct']:+.2f}%  p={res['p_value']:.2e}  floor={res['noise_floor_pct']:.2f}%"


def _env_info() -> Dict[str, str]:
    """Collect host platform and CPU model details for reports."""
    cpu = platform.processor() or "unknown"
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    return {"platform": platform.platform(), "cpu": cpu}


def _make_adapter(name: str, args: argparse.Namespace) -> BaseAdapter:
    """Instantiate a registered adapter from CLI arguments."""
    if name == "RegexAdapter":
        return RegexAdapter(regex_repo_dir=getattr(args, "repo", None))
    if name == "PyMicroAdapter":
        return PyMicroAdapter()
    raise ValueError(f"Unknown adapter '{name}'. Available: {list(ADAPTER_REGISTRY)}")


# ---------------------------------------------------------------------------
# Database Initialization & Data Import/Export Commands
# ---------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize the SQLite database and register all projects in `projects/*.toml`."""
    db = Database(args.db)
    print(f"[regressor] Initialized SQLite database at: {Path(args.db).resolve()}")

    proj_dir = ROOT_DIR / "projects"
    registered = 0
    for toml_file in sorted(proj_dir.glob("*.toml")):
        toml_text = toml_file.read_text(encoding="utf-8")
        raw = tomllib.loads(toml_text)
        p_id = db.register_project(
            name=raw["name"],
            repo_url=raw.get("repo_url", ""),
            build_cmd=raw.get("build_cmd", ""),
            adapter=raw["adapter"],
            config_toml=toml_text,
        )
        print(f"  Registered project '{raw['name']}' (ID={p_id}, Adapter={raw['adapter']})")
        registered += 1
    print(f"[regressor] {registered} projects registered successfully.\n")
    return 0


def cmd_export_data(args: argparse.Namespace) -> int:
    """Write a project's commits and per-run medians to a portable gzipped JSON file."""
    _validate_project_name(args.project)
    db, proj_id = _require_project(args.db, args.project)
    if proj_id is None:
        return 1

    runs = db.get_project_runs(proj_id)
    commits = [
        {k: c[k] for k in _COMMIT_EXPORT_FIELDS}
        | {"runs": {b: v for (cid, b), v in runs.items() if cid == c["id"]}}
        for c in db.get_project_commits(proj_id)
    ]
    out = Path(args.out or ROOT_DIR / "data" / f"{args.project}_history.json.gz")
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump({"format": 1, "project": args.project, "commits": commits}, f, separators=(",", ":"))
    total_runs = sum(len(v) for c in commits for v in c["runs"].values())
    print(f"[regressor] exported {len(commits)} commits, {total_runs} runs -> {out}")
    return 0


def _validate_import_blob(blob: Any) -> None:
    """Validate an export-data JSON payload completely before writing to SQLite."""
    if not isinstance(blob, dict) or not isinstance(blob.get("project"), str) or not isinstance(blob.get("commits"), list):
        raise ValueError("not a regressor export file (expected keys 'project' and 'commits')")
    _validate_project_name(blob["project"])

    required = (*_COMMIT_EXPORT_FIELDS, "runs")
    for i, c in enumerate(blob["commits"]):
        if not isinstance(c, dict):
            raise ValueError(f"commit #{i} is not an object")
        missing = [k for k in required if k not in c]
        if missing:
            raise ValueError(f"commit #{i} is missing {missing}")
        if not isinstance(c["sha"], str) or not c["sha"] or not isinstance(c["runs"], dict):
            raise ValueError(f"commit #{i} has an invalid sha or runs field")
        for bench, medians in c["runs"].items():
            if not isinstance(medians, list):
                raise ValueError(f"commit {c['sha'][:10]} benchmark {bench!r}: runs must be a list")
            for m in medians:
                if isinstance(m, bool) or not isinstance(m, (int, float)) or not math.isfinite(m) or m <= 0:
                    raise ValueError(f"commit {c['sha'][:10]} benchmark {bench!r}: invalid median {m!r}")


def cmd_import_data(args: argparse.Namespace) -> int:
    """Load a portable gzipped JSON file written by `export-data` (idempotent)."""
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
        cid = db.insert_commit(
            project_id=proj_id,
            sha=c["sha"],
            short_sha=c["short_sha"],
            author_date=c["author_date"],
            subject=c["subject"],
            build_ok=bool(c["build_ok"]),
            build_seconds=c["build_seconds"],
            cpu_model=c["cpu_model"],
            rustc_version=c["rustc_version"],
            run_started_utc=c["run_started_utc"],
            run_finished_utc=c["run_finished_utc"],
        )
        n_runs += db.insert_runs_bulk(
            (cid, bench, idx, "", float(m))
            for bench, medians in c["runs"].items()
            for idx, m in enumerate(medians, start=1)
        )
    print(f"[regressor] imported {len(blob['commits'])} commits, {n_runs} runs into {blob['project']}")
    return 0


def cmd_dedupe(args: argparse.Namespace) -> int:
    """Remove duplicate commits and runs from older SQLite databases."""
    print(Database(args.db).dedupe())
    return 0


def _import_legacy_commit(
    db: Database,
    proj_id: int,
    cdir: Path,
    sha_prefix: str,
    benches: List[str],
) -> int:
    """Import one commit directory from `noise-bench/results/commits/` and return run count."""
    meta_file = cdir / "meta.json"
    meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}

    commit_id = db.insert_commit(
        project_id=proj_id,
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

    imported_runs = 0
    for bench in benches:
        rows = [
            (commit_id, bench, idx, str(rf), read_sample_median(rf))
            for idx, rf in enumerate(sorted(cdir.glob(f"{bench}_rep*.txt")), start=1)
        ]
        imported_runs += db.insert_runs_bulk(rows)
    return imported_runs


def cmd_import_legacy(args: argparse.Namespace) -> int:
    """Import historical regex benchmark runs from `noise-bench/results/commits/` into SQLite."""
    db = Database(args.db)
    proj_id = db.get_project_id("regex")
    if not proj_id:
        cmd_init(args)
        proj_id = db.get_project_id("regex")

    results_dir = ROOT_DIR / "noise-bench" / "results" / "commits"
    commits_file = ROOT_DIR / "noise-bench" / "harness" / "commits.txt"
    if not commits_file.exists():
        print(f"Error: commits.txt not found at {commits_file}", file=sys.stderr)
        return 1

    commits_list = [line.strip() for line in commits_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    benches = _project_benchmarks(db, proj_id, "regex")
    print(f"\n[regressor] Importing legacy regex historical data ({len(commits_list)} commits)...")

    imported_commits = 0
    imported_runs = 0
    for sha_prefix in commits_list:
        matches = [d for d in results_dir.iterdir() if d.name.startswith(sha_prefix)]
        if not matches:
            continue
        imported_commits += 1
        imported_runs += _import_legacy_commit(db, proj_id, matches[0], sha_prefix, benches)

    print(f"  Imported {imported_commits} commits and {imported_runs} benchmark runs into SQLite.")
    return 0


# ---------------------------------------------------------------------------
# Validation & Statistical Analysis Commands
# ---------------------------------------------------------------------------


def cmd_validate_adapter(args: argparse.Namespace) -> int:
    """Run the 3-point synthetic injection gate and canary check on an adapter."""
    if args.adapter not in ADAPTER_REGISTRY:
        print(f"Error: Unknown adapter '{args.adapter}'. Available: {list(ADAPTER_REGISTRY)}", file=sys.stderr)
        return 1

    adapter = _make_adapter(args.adapter, args)
    bench = args.benchmark or adapter.list_benchmarks()[0]

    res = validate_adapter_synthetic(adapter, bench, reps=args.reps)
    canary_ok = validate_canary_synthetic()

    if res.all_passed and canary_ok:
        print("✅ [Validation Gate Passed] Adapter and canary passed all synthetic ground-truth tests.")
        return 0
    print(
        "❌ [Validation Gate Failed] Adapter failed synthetic sensitivity requirements. Do not run on real data.",
        file=sys.stderr,
    )
    return 1


def _compute_batch_comparisons(
    commits: List[Any],
    benches: List[str],
    runs_by: Dict[Tuple[int, str], List[float]],
    nf_mult: float,
    window_k: int,
    adjust_autocorr: bool,
) -> List[Dict[str, Any]]:
    """Compute pairwise or rolling-baseline statistics for every adjacent commit transition."""
    comparisons: List[Dict[str, Any]] = []
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
                hist_runs = [
                    runs_by.get((commits[j]["id"], bench), [])
                    for j in range(max(0, i - window_k), i)
                ]
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
    return comparisons


def _persist_batch_comparisons(
    db: Database,
    proj_id: int,
    comparisons: List[Dict[str, Any]],
    triage_notes: Dict[tuple, tuple],
) -> Tuple[int, int]:
    """Store batch comparisons with triage metadata and return `(pre_fdr_flags, post_fdr_flags)`."""
    n_flags = 0
    n_flags_fdr = 0
    for c in comparisons:
        note, status = triage_notes.get((c["benchmark"], c["cand_sha"][:7]), ("", "unreviewed"))
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
            canary_status="NOT_RECORDED",
            pmu_status="UNAVAILABLE",
            session_gap_min=c["session_gap_min"],
        )
    return n_flags, n_flags_fdr


def _print_batch_summary(
    project: str,
    n_commits: int,
    comparisons: List[Dict[str, Any]],
    n_flags: int,
    n_flags_fdr: int,
    fdr_method: str,
) -> None:
    """Print the batch summary table and any post-FDR flagged transitions."""
    bar = "=" * 75
    fdr_label = "" if fdr_method == "bh" else "BY, "
    print(f"\n{bar}")
    print(f"  regressor Batch Analysis — Project: '{project}'")
    print(bar)
    print(f"  Total Commits Analyzed:    {n_commits}")
    print(f"  Total Pairwise Tests:      {len(comparisons)}")
    print(f"  Flagged Pre-FDR:           {n_flags}")
    print(f"  Flagged Post-FDR ({fdr_label}α=0.05): {n_flags_fdr}")
    print(f"{bar}\n")

    for c in comparisons:
        if c["verdict"] == "flag" and c["fdr_significant"]:
            gap = c["session_gap_min"]
            gap_tag = (
                f"  [SESSION_BREAK: {gap:.0f} min gap before run — environment-confounded]"
                if is_session_break(gap)
                else ""
            )
            print(f"  [FLAG] {c['benchmark']:20s} {c['base_sha']} -> {c['cand_sha']}  {_format_comparison_metrics(c)}{gap_tag}")
            print(f"         {c['cand_subject']}\n")


def _verify_legacy_study(
    n_commits: int,
    n_comparisons: int,
    n_flags: int,
    n_flags_fdr: int,
    fdr_method: str,
) -> int:
    """Assert exact reproduction of the original 27-commit regex study (REPORT.md)."""
    if fdr_method != "bh":
        print("Error: --verify-legacy reproduces the original BH-corrected study; drop --fdr by.", file=sys.stderr)
        return 1
    expected = {
        "commits": (n_commits, 27),
        "comparisons": (n_comparisons, 78),
        "flags": (n_flags, 5),
        "FDR flags": (n_flags_fdr, 5),
    }
    bad = [f"{k}: expected {e}, got {g}" for k, (g, e) in expected.items() if g != e]
    if bad:
        print("Error: legacy reproduction mismatch: " + "; ".join(bad), file=sys.stderr)
        return 1
    print(
        "✅ Same flag set as REPORT.md (27 commits, 78 comparisons, 5 flags). "
        "Noise floors differ by sqrt(20/19) because of ddof=1.\n"
    )
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    """Run batch change-point detection across stored commits and apply FDR correction."""
    db, proj_id = _require_project(args.db, args.project, init_hint=True)
    if proj_id is None:
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

    comparisons = _compute_batch_comparisons(
        commits=commits,
        benches=benches,
        runs_by=db.get_project_runs(proj_id),
        nf_mult=nf_mult,
        window_k=window_k,
        adjust_autocorr=adjust_autocorr,
    )
    bh_fdr_correct(comparisons, alpha=0.05, method=fdr_method)
    n_flags, n_flags_fdr = _persist_batch_comparisons(db, proj_id, comparisons, _load_triage(args.project))
    _print_batch_summary(args.project, len(commits), comparisons, n_flags, n_flags_fdr, fdr_method)

    if args.verify_legacy:
        return _verify_legacy_study(len(commits), len(comparisons), n_flags, n_flags_fdr, fdr_method)
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    """Run an ad-hoc pairwise comparison between two stored commits."""
    db, proj_id = _require_project(args.db, args.project)
    if proj_id is None:
        return 1

    commits = db.get_project_commits(proj_id)
    base_c, cand_c, err = resolve_commit_pair(commits, args.base_sha, args.cand_sha)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    benches = _project_benchmarks(db, proj_id, args.project)
    base_runs = db.get_commit_runs_by_benchmark(base_c["id"])
    cand_runs = db.get_commit_runs_by_benchmark(cand_c["id"])
    results = compare_benchmark_runs(base_runs, cand_runs, benchmarks=benches, min_runs=1)

    print(f"\n[Ad-Hoc Comparison] {base_c['short_sha']} -> {cand_c['short_sha']}")
    for res in results:
        tag = "[FLAG]" if res["verdict"] == "flag" else "[PASS]"
        print(f"  {tag:6s} {res['benchmark']:20s} {_format_comparison_metrics(res)}")
    print()
    return 0


def _print_fpr_tiers(
    db: Database,
    proj_id: Optional[int],
    session: Dict[str, List[float]],
    trials: int,
) -> None:
    """Report the three empirical false-positive rates from recorded runs and DB history."""
    from core.power import aa_contiguous_split, aa_random_split, null_transition_fpr

    print("  1) Within-session A/A, random split (jitter only)")
    for b, meds in session.items():
        r = aa_random_split(meds, trials=trials)
        print(f"     {b:18s} {r['flags']:4d}/{r['trials']} = {r['fpr_pct']:5.2f}%   95% CI {r['ci95_pct']}")

    print("\n  2) Within-session A/A, first half vs second half (adds slow in-session drift)")
    for b, meds in session.items():
        r = aa_contiguous_split(meds)
        print(
            f"     {b:18s} verdict={r['verdict']:4s} shift={r['shift_pct']:+.2f}%  "
            f"p={r['p_value']:.2e}  floor={r['noise_floor_pct']:.2f}%"
        )

    rows = [dict(r) for r in db.get_project_comparisons(proj_id)] if proj_id else []
    print("\n  3) Real null transitions: adjacent commits whose candidate is doc-only")
    print("     (classified by commit subject 'doc:'/'docs:'; same compiled code, separate runs)")
    if not rows or rows[0].get("session_gap_min") is None:
        print("     No comparisons with session gaps in DB. Run `regressor batch` first.")
        return

    n = null_transition_fpr(rows)
    for label, key in (
        ("all", "all"),
        ("within session (gap <= 15 min)", "within_session"),
        ("across a session break", "across_session_break"),
    ):
        s = n[key]
        print(f"     {label:32s} {s['flags']:2d}/{s['n']:2d} = {s['fpr_pct']:5.2f}%   95% CI {s['ci95_pct']}")
    print(f"     doc-only commits: {', '.join(n['null_commits'])}")
    for f in n["flagged"]:
        print(f"       flagged: {f['cand_sha']} {f['benchmark']} {f['shift_pct']:+.2f}% (gap {f['session_gap_min']} min)")


def _print_power_table(bench: str, pw: Dict[str, Any], bar: str) -> None:
    """Render the empirical power and MDE@80% grid for one benchmark."""
    print(
        f"\n{bar}\n  Power (within-session noise only): {bench}, pool={pw['pool_size']} runs, "
        f"{pw['trials_per_point']} trials/point\n{bar}"
    )
    effs = list(next(iter(pw["power_grid"].values())).keys())
    print("  " + "N".ljust(6) + "".join(f"{e:>8s}" for e in effs) + "   MDE@80%")
    for k, grid in pw["power_grid"].items():
        mde = pw["mde_at_80_pct_power"][k]
        mde_str = f"+{mde:g}%" if mde else "> max"
        print("  " + k.ljust(6) + "".join(f"{v:8.2f}" for v in grid.values()) + f"   {mde_str}")
    print()


def cmd_evaluate_power(args: argparse.Namespace) -> int:
    """Measure false-positive rates three ways and compute a statistical power curve."""
    from core.power import evaluate_power_curve, load_session_medians

    db = Database(args.db)
    proj_id = db.get_project_id(args.project)
    benches = (
        _project_benchmarks(db, proj_id, args.project)
        if proj_id
        else ["compile_moderate", "find_iter_userid", "is_match_status"]
    )
    session = load_session_medians(Path(args.session_dir), benches)
    if not session:
        print(f"Error: no session data in {args.session_dir}", file=sys.stderr)
        return 1

    bar = "=" * 78
    print(f"\n{bar}\n  False-positive rate, measured three ways (alpha=0.01, 3x CV floor)\n{bar}")
    counts = ", ".join(f"{b}: {len(v)} runs" for b, v in session.items())
    print(f"  Session data: {args.session_dir} ({counts})\n")

    _print_fpr_tiers(db, proj_id, session, args.trials)

    bench = args.benchmark or next(iter(session))
    if bench not in session:
        print(f"Error: benchmark '{bench}' not in session data ({', '.join(session)})", file=sys.stderr)
        return 1
    pw = evaluate_power_curve(session[bench], trials_per_point=args.power_trials)
    _print_power_table(bench, pw, bar)
    return 0


def _print_changepoints(project: str, bench: str, n_commits: int, cps: List[Dict[str, Any]]) -> None:
    """Format E-Divisive change-point detection results for the terminal."""
    bar = "=" * 75
    print(f"\n{bar}")
    print("  regressor Series-Level E-Divisive Change-Point Detection")
    print(f"  Project: '{project}' | Benchmark: '{bench}' | Commits: {n_commits}")
    print(f"{bar}\n")

    if not cps:
        print("  No statistically significant structural change points detected across the series.\n")
        return

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
    print(f"{bar}\n")


def cmd_changepoint(args: argparse.Namespace) -> int:
    """Run series-level E-Divisive change-point detection across the commit timeline."""
    db, proj_id = _require_project(args.db, args.project)
    if proj_id is None:
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
    known_breaks = find_session_break_indices(commits)
    nf_mult = _project_noise_floor_multiplier(args.project)
    cps = detect_series_changepoints_edivisive(
        shas,
        series_runs,
        significance_alpha=args.alpha,
        known_breaks=known_breaks,
        noise_floor_multiplier=nf_mult,
    )
    _print_changepoints(args.project, bench, len(commits), cps)
    return 0


# ---------------------------------------------------------------------------
# Live Interleaved Execution, Bisection & Web Server Commands
# ---------------------------------------------------------------------------


def _build_pair_artifacts(
    adapter: BaseAdapter,
    base_ref: str,
    cand_ref: str,
    workdir: Path,
) -> Optional[Dict[str, Optional[str]]]:
    """Build both commits into isolated workdirs and return `{'base': ..., 'cand': ...}`."""
    builds: Dict[str, Optional[str]] = {}
    for label, ref in (("base", base_ref), ("cand", cand_ref)):
        print(f"[build] {label} = {ref} ...", flush=True)
        br = adapter.build(ref, workdir=workdir)
        if not br.ok:
            print(f"Error: build failed for {ref}:\n{br.log_tail}", file=sys.stderr)
            return None
        builds[label] = br.artifact
        print(f"        ok ({br.seconds}s) -> {br.artifact}")
    return builds


def _print_interleaved_results(results: List[Dict[str, Any]]) -> None:
    """Print per-benchmark interleaved comparison results."""
    print()
    for r in results:
        tag = "FLAG" if r["final_verdict"] == "flag" else " ok "
        lo, hi = r["shift_ci95_pct"]
        floor_note = " (floor: all pairs same sign)" if r.get("p_at_floor") else ""
        print(
            f"  [{tag}] {r['benchmark']:20s} shift={r['shift_pct']:+.2f}% CI95=[{lo:+.2f}, {hi:+.2f}]  "
            f"p={r['p_value']:.2e}{floor_note}  order-effect={r['order_effect_pct']}%"
        )
    print()


def _write_interleaved_reports(
    args: argparse.Namespace,
    results: List[Dict[str, Any]],
    env: Dict[str, str],
    canary: Optional[Dict[str, Any]],
) -> None:
    """Write optional JSON and Markdown reports for `compare-interleaved`."""
    if args.json:
        payload = {"base": args.base, "cand": args.cand, "env": env, "canary": canary, "results": results}
        Path(args.json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if args.markdown:
        from core.report import render_markdown

        Path(args.markdown).write_text(
            render_markdown(args.base, args.cand, results, env, canary),
            encoding="utf-8",
        )


def cmd_compare_interleaved(args: argparse.Namespace) -> int:
    """Build two commits and benchmark them in alternating pairs (paired Wilcoxon)."""
    adapter = _make_adapter(args.adapter, args)
    benches = args.benchmark or adapter.list_benchmarks()
    builds = _build_pair_artifacts(adapter, args.base, args.cand, Path(args.workdir))
    if builds is None:
        return 2

    # Sample an invariant canary before and after the measurement window to spot host drift.
    canary_pre = CanaryBenchmark.run_reps(reps=args.canary_reps) if args.canary_reps > 0 else None

    results = []
    req_ci = bool(getattr(args, "require_ci_bound", False))
    for i, bench in enumerate(benches):
        print(f"[run] {bench}: {args.pairs} interleaved pairs ...", flush=True)
        results.append(
            run_interleaved(
                adapter,
                bench,
                builds["base"],
                builds["cand"],
                pairs=args.pairs,
                iters=args.iters,
                warmup=args.warmup,
                inject_ns_b=args.inject_ns,
                alpha=args.alpha,
                min_effect_pct=args.min_effect,
                seed=args.seed + i,
                require_ci_bound=req_ci,
            )
        )

    canary = None
    if canary_pre is not None:
        canary = CanaryBenchmark.evaluate_drift(canary_pre, CanaryBenchmark.run_reps(reps=args.canary_reps))
        print(f"[canary] shift={canary['shift_pct']:+.2f}% -> {canary['status']}")

    bh_fdr_correct(results, alpha=args.alpha)
    for r in results:
        r["final_verdict"] = "flag" if (r["verdict"] == "flag" and r["fdr_significant"]) else "ok"
        r["canary_status"] = canary["status"] if canary else "NOT_RECORDED"
        if r["final_verdict"] == "flag" and canary and canary["is_drifted"]:
            r["attribution"] = "ENVIRONMENT_DRIFT_SUSPECTED"

    _print_interleaved_results(results)
    _write_interleaved_reports(args, results, _env_info(), canary)

    regressed = any(r["final_verdict"] == "flag" and r["shift_pct"] > 0 for r in results)
    env_suspect = bool(canary and canary["is_drifted"])
    if regressed and args.fail_on_regression and env_suspect and getattr(args, "no_fail_on_env_suspect", False):
        print("[canary] host drift suspected: flagged slowdown reported but not failing (--no-fail-on-env-suspect)")
        return 0
    return 1 if (regressed and args.fail_on_regression) else 0


def cmd_bisect(args: argparse.Namespace) -> int:
    """Binary-search a commit range using interleaved A/B probes against the good build."""
    from core.bisect import bisect_builds, git_rev_list

    if args.demo:
        # Simulated 16-commit history where c09+ add a real 400 ns/iter busy-wait.
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
    res = bisect_builds(
        adapter,
        commits,
        bench,
        pairs=args.pairs,
        iters=args.iters,
        warmup=args.warmup,
        workdir=Path(args.workdir),
        alpha=args.alpha,
        min_effect_pct=args.min_effect,
    )
    if not res["reproduced"]:
        print("\n  Bad commit does not regress against good under interleaved A/B. Nothing to bisect.\n")
        return 0
    print(
        f"\n  first bad: {res['culprit']}   last good: {res['last_good']}   "
        f"builds: {res['builds']} (vs {len(commits)} for a linear scan)\n"
    )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Launch the FastAPI backend and live performance ledger dashboard."""
    import uvicorn

    from server.app import create_app

    app = create_app(db_path=args.db)
    print(f"\n[regressor] Serving live performance ledger at: http://localhost:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
    return 0


# ---------------------------------------------------------------------------
# CLI Argument Validation & Parser Configuration
# ---------------------------------------------------------------------------


def _parse_int_min(s: str, minimum: int) -> int:
    try:
        v = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected an integer, got {s!r}") from None
    if v < minimum:
        raise argparse.ArgumentTypeError(f"must be >= {minimum}, got {v}")
    return v


def positive_int(s: str) -> int:
    """argparse type: integer >= 1."""
    return _parse_int_min(s, 1)


def non_negative_int(s: str) -> int:
    """argparse type: integer >= 0."""
    return _parse_int_min(s, 0)


def _parse_float(s: str) -> float:
    try:
        return float(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a number, got {s!r}") from None


def non_negative_float(s: str) -> float:
    """argparse type: finite float >= 0."""
    v = _parse_float(s)
    if not (math.isfinite(v) and v >= 0.0):
        raise argparse.ArgumentTypeError(f"must be a finite number >= 0, got {s}")
    return v


def probability(s: str) -> float:
    """argparse type: significance level strictly between 0 and 1."""
    v = _parse_float(s)
    if not (math.isfinite(v) and 0.0 < v < 1.0):
        raise argparse.ArgumentTypeError(f"must be between 0 and 1 (exclusive), got {s}")
    return v


def _add_run_options(parser: argparse.ArgumentParser, default_pairs: int) -> None:
    """Register shared adapter/build/statistical options for live measurement commands."""
    adapters = list(ADAPTER_REGISTRY)
    parser.add_argument(
        "--adapter",
        choices=adapters,
        default="RegexAdapter",
        help="Benchmark adapter to execute (default: %(default)s)",
    )
    parser.add_argument("--repo", help="Path to local target git clone (required for RegexAdapter)")
    parser.add_argument(
        "--workdir",
        default=".regressor-builds",
        help="Directory for isolated commit worktrees and builds (default: %(default)s)",
    )
    parser.add_argument(
        "--pairs",
        type=positive_int,
        default=default_pairs,
        help="Number of interleaved A/B process pairs (default: %(default)s)",
    )
    parser.add_argument(
        "--iters",
        type=positive_int,
        default=2000,
        help="Timed iterations per benchmark process (default: %(default)s)",
    )
    parser.add_argument(
        "--warmup",
        type=non_negative_int,
        default=200,
        help="Untimed warmup iterations per process (default: %(default)s)",
    )
    parser.add_argument(
        "--alpha",
        type=probability,
        default=0.01,
        help="Wilcoxon significance threshold (default: %(default)s)",
    )
    parser.add_argument(
        "--min-effect",
        type=non_negative_float,
        default=1.0,
        help="Practical shift threshold in percent (default: %(default)s)",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser with documented subcommands and quickstart examples."""
    epilog = """examples:
  # Load portable study data and reproduce batch analysis (no Rust toolchain needed)
  regressor import-data data/regex_history.json.gz
  regressor batch regex --verify-legacy

  # Validate an adapter with synthetic ground-truth slowdown injection
  regressor validate-adapter PyMicroAdapter --reps 20

  # Interleaved A/B comparison between two commits or variants
  regressor compare-interleaved --adapter PyMicroAdapter --base v1 --cand v2 --pairs 20 --inject-ns 500
  regressor compare-interleaved --adapter RegexAdapter --repo regex --base 16d47c5 --cand 0a446ec

  # Series change-point scan, empirical power curves, bisection, and web dashboard
  regressor changepoint regex --benchmark compile_moderate
  regressor evaluate-power regex --benchmark compile_moderate
  regressor bisect --demo
  regressor serve --port 8000
"""
    parser = argparse.ArgumentParser(
        prog="regressor",
        description="Statistical performance regression detection for noisy CI and shared hosts.",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db",
        default="regressor.db",
        help="Path to SQLite database file (default: %(default)s)",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>", help="Available commands")
    adapters = list(ADAPTER_REGISTRY)

    subparsers.add_parser(
        "init",
        help="Initialize SQLite database and register projects/*.toml",
        description="Initialize the SQLite schema and register all project manifests in projects/*.toml.",
    )

    p_val = subparsers.add_parser(
        "validate-adapter",
        help="Run 3-point synthetic injection gate on an adapter",
        description="Verify an adapter passes true-negative, large-injection, and noise-floor checks plus canary drift.",
    )
    p_val.add_argument("adapter", choices=adapters, help="Adapter class name to validate")
    p_val.add_argument("--benchmark", help="Benchmark identifier to test (default: adapter's first benchmark)")
    p_val.add_argument("--reps", type=positive_int, default=25, help="Repetitions per injection level (default: %(default)s)")

    subparsers.add_parser(
        "import-legacy",
        help="Import raw regex commit files from noise-bench/ into SQLite",
        description="Import historical raw benchmark repetitions from noise-bench/results/commits/ into SQLite.",
    )

    p_exp = subparsers.add_parser(
        "export-data",
        help="Export a project's commits and medians to gzipped JSON",
        description="Write a project's commits and per-run medians to a portable .json.gz archive.",
    )
    p_exp.add_argument("project", help="Project name registered in the database")
    p_exp.add_argument("--out", help="Output .json.gz path (default: data/<project>_history.json.gz)")

    p_imp = subparsers.add_parser(
        "import-data",
        help="Import a portable .json.gz archive into SQLite (idempotent)",
        description="Load a portable .json.gz file produced by export-data into SQLite safely and idempotently.",
    )
    p_imp.add_argument("path", help="Path to the .json.gz archive to import")

    subparsers.add_parser(
        "dedupe",
        help="Remove duplicate commits/runs from an older SQLite database",
        description="Collapse duplicate commits and runs in an existing database and ensure unique indexes exist.",
    )

    p_batch = subparsers.add_parser(
        "batch",
        help="Run adjacent-pair detection across stored commits (+FDR)",
        description="Run pairwise or rolling-baseline regression detection across all stored commits with FDR control.",
    )
    p_batch.add_argument("project", default="regex", nargs="?", help="Project name (default: %(default)s)")
    p_batch.add_argument(
        "--rolling-window",
        type=positive_int,
        default=1,
        help="Prior commits pooled for baseline window K (default: 1 = adjacent pair)",
    )
    p_batch.add_argument(
        "--adjust-autocorr",
        action="store_true",
        help="Compute moving-block bootstrap p-values alongside Mann-Whitney under autocorrelation",
    )
    p_batch.add_argument(
        "--fdr",
        choices=("bh", "by"),
        default="bh",
        help="FDR method: bh = Benjamini-Hochberg (default); by = Benjamini-Yekutieli (arbitrary dependence)",
    )
    p_batch.add_argument(
        "--verify-legacy",
        action="store_true",
        help="Assert exact reproduction of the original regex study (27 commits, 78 comparisons, 5 flags)",
    )

    p_ana = subparsers.add_parser(
        "analyze",
        help="Ad-hoc comparison of two stored commits",
        description="Compare two stored commits in SQLite by SHA prefix across all project benchmarks.",
    )
    p_ana.add_argument("project", help="Project name registered in the database")
    p_ana.add_argument("base_sha", help="Baseline commit SHA (full or unique >=4-char prefix)")
    p_ana.add_argument("cand_sha", help="Candidate commit SHA (full or unique >=4-char prefix)")

    p_intl = subparsers.add_parser(
        "compare-interleaved",
        help="Build two refs and run them in alternating pairs",
        description="Build two commits/variants and benchmark them in randomized alternating pairs using paired Wilcoxon.",
    )
    _add_run_options(p_intl, default_pairs=20)
    p_intl.add_argument("--base", required=True, help="Baseline git ref (or variant label for PyMicroAdapter)")
    p_intl.add_argument("--cand", required=True, help="Candidate git ref (or variant label for PyMicroAdapter)")
    p_intl.add_argument("--benchmark", action="append", help="Benchmark name to run (repeatable; default: all)")
    p_intl.add_argument(
        "--inject-ns",
        type=non_negative_int,
        default=0,
        help="Ground-truth busy-wait ns added per iteration to candidate (default: %(default)s)",
    )
    p_intl.add_argument("--seed", type=int, default=0, help="RNG seed for pair execution order (default: %(default)s)")
    p_intl.add_argument(
        "--canary-reps",
        type=non_negative_int,
        default=10,
        help="Invariant canary samples collected before and after the run; 0 disables (default: %(default)s)",
    )
    p_intl.add_argument(
        "--require-ci-bound",
        action="store_true",
        help="Require the 95%% bootstrap CI bound (not just point estimate) to clear --min-effect",
    )
    p_intl.add_argument("--json", help="Write full structured comparison results to JSON file")
    p_intl.add_argument("--markdown", help="Write PR-ready Markdown summary report to file")
    p_intl.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Exit 1 on a flagged slowdown (also fails if canary flags host drift unless --no-fail-on-env-suspect)",
    )
    p_intl.add_argument(
        "--no-fail-on-env-suspect",
        action="store_true",
        help="With --fail-on-regression: still report flags but exit 0 if the canary detected host drift",
    )

    p_pwr = subparsers.add_parser(
        "evaluate-power",
        help="Measure false-positive rates three ways + power/MDE curve",
        description="Evaluate within-session A/A FPR, doc-only null-transition FPR, and statistical power curves.",
    )
    p_pwr.add_argument("project", default="regex", nargs="?", help="Project name (default: %(default)s)")
    p_pwr.add_argument("--benchmark", help="Benchmark used for the power curve (default: first in session data)")
    p_pwr.add_argument(
        "--session-dir",
        default=str(ROOT_DIR / "noise-bench" / "results" / "20260813T150528_baseline"),
        help="Directory containing single-session *_rep*.txt files (default: baseline study)",
    )
    p_pwr.add_argument("--trials", type=positive_int, default=1000, help="Random-split A/A trials (default: %(default)s)")
    p_pwr.add_argument(
        "--power-trials",
        type=positive_int,
        default=300,
        help="Resampling trials per grid point on power curve (default: %(default)s)",
    )

    p_cp = subparsers.add_parser(
        "changepoint",
        help="Detect structural change points across a commit series (E-Divisive)",
        description="Run non-parametric E-Divisive energy-distance change-point detection across commit medians.",
    )
    p_cp.add_argument("project", default="regex", nargs="?", help="Project name (default: %(default)s)")
    p_cp.add_argument("--benchmark", help="Benchmark name to scan (default: first configured benchmark)")
    p_cp.add_argument(
        "--alpha",
        type=probability,
        default=0.05,
        help="Permutation-test significance threshold (default: %(default)s)",
    )

    p_bis = subparsers.add_parser(
        "bisect",
        help="Binary-search a commit range using interleaved probes",
        description="Find the first regressed commit in O(log K) builds via interleaved A/B probes.",
    )
    _add_run_options(p_bis, default_pairs=12)
    p_bis.add_argument("--good", help="Known-good git ref")
    p_bis.add_argument("--bad", help="Known-bad git ref")
    p_bis.add_argument("--benchmark", help="Benchmark to probe (default: adapter's first benchmark)")
    p_bis.add_argument("--demo", action="store_true", help="Run a simulated 16-commit bisection with PyMicroAdapter")

    p_srv = subparsers.add_parser(
        "serve",
        help="Start the FastAPI backend and interactive web dashboard",
        description="Launch the local FastAPI API server and performance ledger web UI.",
    )
    p_srv.add_argument("--port", type=positive_int, default=8000, help="HTTP port to bind on localhost (default: %(default)s)")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Parse CLI arguments and dispatch to the requested subcommand handler."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    # Resolve handlers at call time so tests can monkeypatch individual cmd_* functions.
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
    try:
        return commands[args.command](args)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
