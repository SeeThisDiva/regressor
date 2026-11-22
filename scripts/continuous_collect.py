#!/usr/bin/env python3
"""
scripts/continuous_collect.py
Incremental upstream commit collector and statistical detection runner.

Reads the latest recorded commit from an existing `.json.gz` study archive (or
explicit `--since-sha`), fetches new commits from the upstream git remote,
profiles every newly discovered commit in an isolated worktree via `RegexAdapter`,
runs batch FDR + E-Divisive change-point detection, exports the updated archive,
and writes sanitized JSON/Markdown summary reports.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import regressor  # noqa: E402
from adapters.base import BaseAdapter  # noqa: E402
from adapters.regex_adapter import RegexAdapter  # noqa: E402
from core.bisect import validate_git_ref  # noqa: E402
from core.canary import CanaryBenchmark  # noqa: E402
from core.db import Database  # noqa: E402
from core.report import _safe_md  # noqa: E402
from core.series_detector import detect_series_changepoints_edivisive  # noqa: E402
from core.session import find_session_break_indices, is_session_break  # noqa: E402

DATASET_CANDIDATES = (
    "data/regex_continuous_history.json.gz",
    "data/regex_study3_history.json.gz",
    "data/regex_study2_history.json.gz",
    "data/regex_history.json.gz",
)


def _dataset_latest_timestamp(path: Path) -> str:
    """Return the ISO timestamp of the newest commit inside ``path``, or '' on empty."""
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            blob = json.load(fh)
        commits = blob.get("commits") or []
        if not commits:
            return ""
        dt = datetime.fromisoformat(commits[-1]["author_date"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return ""


def resolve_dataset_path(dataset_arg: str, root_dir: Path = ROOT_DIR) -> Optional[Path]:
    """Resolve ``--dataset`` (`auto` picks newest available study archive, or explicit path)."""
    if dataset_arg and dataset_arg != "auto":
        p = Path(dataset_arg)
        if not p.is_absolute():
            p = root_dir / p
        if not p.exists():
            raise FileNotFoundError(f"Dataset archive not found: {p}")
        return p

    existing = [root_dir / rel for rel in DATASET_CANDIDATES if (root_dir / rel).exists()]
    if not existing:
        return None
    # Pick whichever archive ends at the newest commit date (breaking ties by DATASET_CANDIDATES order).
    best_idx = max(range(len(existing)), key=lambda i: (_dataset_latest_timestamp(existing[i]), -i))
    return existing[best_idx]


def load_recorded_state(dataset_path: Path) -> Tuple[Optional[str], set[str], List[Dict[str, Any]]]:
    """Read and validate an exported ``.json.gz`` dataset, returning ``(last_sha, sha_set, commits)``."""
    with gzip.open(dataset_path, "rt", encoding="utf-8") as fh:
        blob = json.load(fh)
    regressor._validate_import_blob(blob)
    commits = blob["commits"]
    known_shas = {c["sha"] for c in commits}
    last_sha = commits[-1]["sha"] if commits else None
    return last_sha, known_shas, commits


def _git_env() -> Dict[str, str]:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _run_git(repo_dir: Path, args: Sequence[str], timeout: int = 120) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        env=_git_env(),
        timeout=timeout,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {err}")
    return proc.stdout


def discover_new_commits(
    repo_dir: Path,
    since_sha: Optional[str],
    *,
    remote: str = "origin",
    branch: str = "master",
    fetch: bool = True,
    max_commits: int = 0,
) -> List[Dict[str, str]]:
    """Fetch upstream if requested and return chronological metadata for commits after ``since_sha``."""
    if not (repo_dir / ".git").exists():
        raise FileNotFoundError(f"Git repository not found at {repo_dir}")

    validate_git_ref(remote)
    validate_git_ref(branch)
    if since_sha:
        validate_git_ref(since_sha)

    if fetch:
        _run_git(repo_dir, ["fetch", "--quiet", remote, branch], timeout=300)
        target_ref = f"{remote}/{branch}"
    else:
        target_ref = "HEAD"

    validate_git_ref(target_ref)
    if since_sha:
        rev_range = f"{since_sha}..{target_ref}"
        out = _run_git(repo_dir, ["rev-list", "--reverse", "--first-parent", rev_range])
    else:
        out = _run_git(repo_dir, ["rev-list", "--reverse", "--first-parent", "-n", "1", target_ref])

    shas = [line.strip() for line in out.splitlines() if line.strip()]
    if max_commits > 0:
        shas = shas[:max_commits]

    commits: List[Dict[str, str]] = []
    for sha in shas:
        validate_git_ref(sha)
        meta_line = _run_git(repo_dir, ["show", "-s", "--format=%H%x00%aI%x00%s", sha, "--"]).strip()
        parts = meta_line.split("\x00", 2)
        if len(parts) != 3:
            raise RuntimeError(f"Unexpected git show metadata for {sha}: {meta_line!r}")
        full_sha, author_date, subject = parts
        commits.append(
            {
                "sha": full_sha,
                "short_sha": full_sha[:7],
                "author_date": author_date,
                "subject": subject,
            }
        )
    return commits


def _rustc_version_string() -> str:
    try:
        proc = subprocess.run(["rustc", "--version"], capture_output=True, text=True, timeout=15)
        return proc.stdout.strip() if proc.returncode == 0 else "unknown"
    except (FileNotFoundError, OSError):
        return "not installed"


def _cleanup_commit_worktree(repo_dir: Path, workdir: Path, sha: str) -> None:
    """Remove an isolated commit worktree/target directory after benchmarking to keep CI disk bounded."""
    commit_root = workdir.resolve() / sha[:12]
    wt_dir = commit_root / "regex"
    if wt_dir.exists() and (repo_dir / ".git").exists():
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(wt_dir)],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            env=_git_env(),
            timeout=60,
        )
    if commit_root.exists():
        shutil.rmtree(commit_root, ignore_errors=True)
    if (repo_dir / ".git").exists():
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            env=_git_env(),
            timeout=60,
        )


def _render_summary_markdown(summary: Dict[str, Any]) -> str:
    """Render a sanitized Markdown summary of continuous collection + detection results."""
    lines = [
        "### regressor Continuous Collection Summary",
        "",
        f"- **Project:** `{_safe_md(summary['project'])}`",
        f"- **Baseline Dataset:** `{_safe_md(summary['source_dataset'] or 'none')}`",
        f"- **Anchor Commit:** `{_safe_md((summary['since_sha'] or 'HEAD')[:10])}`",
        f"- **Commits Discovered:** {summary['commits_discovered']} "
        f"(Profiled: {summary['commits_profiled']}, Skipped: {summary['commits_skipped']}, "
        f"Build Failed: {summary['commits_build_failed']})",
        f"- **Benchmarks ({len(summary['benchmarks'])}):** "
        + ", ".join(f"`{_safe_md(b)}`" for b in summary["benchmarks"]),
        f"- **Total Commits in DB:** {summary['total_commits']} | "
        f"**Comparisons:** {summary['total_comparisons']} | "
        f"**Post-FDR Flags ({_safe_md(summary['fdr'].upper())}):** {summary['post_fdr_flags']}",
        "",
    ]

    if summary["collected"]:
        lines += [
            "#### Newly Processed Commits",
            "",
            "| Commit | Date | Build | Canary | Subject |",
            "|---|---|---|---:|---|",
        ]
        for entry in summary["collected"]:
            build_str = f"ok ({entry['build_seconds']}s)" if entry["build_ok"] else "FAILED"
            canary_str = _safe_md(entry.get("canary_status", "NOT_RECORDED"))
            lines.append(
                f"| `{_safe_md(entry['short_sha'])}` | `{_safe_md(entry['author_date'][:10])}` | "
                f"{build_str} | {canary_str} | {_safe_md(entry['subject'])} |"
            )
        lines.append("")

    if summary["flagged"]:
        lines += [
            "#### Post-FDR Flagged Transitions",
            "",
            "| Benchmark | Transition | Shift | p-value | Note |",
            "|---|---|---:|---:|---|",
        ]
        for fl in summary["flagged"]:
            gap = fl.get("session_gap_min")
            note = f"SESSION_BREAK ({gap:.0f}m)" if is_session_break(gap) else "review"
            lines.append(
                f"| `{_safe_md(fl['benchmark'])}` | `{_safe_md(fl['base_sha'])} -> {_safe_md(fl['cand_sha'])}` | "
                f"{fl['shift_pct']:+.2f}% | {fl['p_value']:.2e} | {note} |"
            )
        lines.append("")

    if summary["changepoints"]:
        lines += [
            "#### E-Divisive Change-Points",
            "",
        ]
        for cp in summary["changepoints"]:
            lines.append(
                f"- `{_safe_md(cp['benchmark'])}` @ `{_safe_md(cp['commit_sha'])}`: "
                f"{cp['shift_pct']:+.2f}% (p={cp['permutation_p_value']:.4f})"
            )
        lines.append("")

    return "\n".join(lines) + "\n"


def run_continuous_collection(
    *,
    project: str = "regex",
    dataset_arg: str = "auto",
    out_dataset: Optional[Path] = None,
    db_path: Path = Path("noise-bench/results/continuous.db"),
    repo_dir: Path = Path("regex"),
    remote: str = "origin",
    branch: str = "master",
    since_sha: Optional[str] = None,
    fetch: bool = True,
    max_commits: int = 0,
    benchmarks_override: Optional[List[str]] = None,
    reps: int = 15,
    iters: int = 1500,
    warmup: int = 150,
    canary_reps: int = 5,
    fdr: str = "by",
    workdir: Path = Path(".regressor-builds"),
    cleanup_worktrees: bool = True,
    summary_json: Optional[Path] = None,
    summary_md: Optional[Path] = None,
    adapter: Optional[BaseAdapter] = None,
    root_dir: Path = ROOT_DIR,
) -> Dict[str, Any]:
    """Execute one incremental upstream collection + batch/changepoint detection + export cycle."""
    regressor._validate_project_name(project)
    repo_dir = repo_dir if repo_dir.is_absolute() else (root_dir / repo_dir)
    db_path = db_path if db_path.is_absolute() else (root_dir / db_path)
    workdir = workdir if workdir.is_absolute() else (root_dir / workdir)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    source_dataset = resolve_dataset_path(dataset_arg, root_dir=root_dir)
    known_shas: set[str] = set()
    dataset_last_sha: Optional[str] = None
    if source_dataset is not None:
        dataset_last_sha, known_shas, _ = load_recorded_state(source_dataset)
        rc = regressor.cmd_import_data(argparse.Namespace(db=str(db_path), path=str(source_dataset)))
        if rc != 0:
            raise RuntimeError(f"Failed importing baseline dataset {source_dataset}")

    db = Database(str(db_path))
    proj_id = db.get_project_id(project)
    if proj_id is None:
        regressor.cmd_init(argparse.Namespace(db=str(db_path)))
        proj_id = db.get_project_id(project)
    if proj_id is None:
        raise RuntimeError(f"Project '{project}' not found in projects/{project}.toml")

    db_commits = db.get_project_commits(proj_id)
    known_shas.update(c["sha"] for c in db_commits)
    anchor_sha = since_sha or dataset_last_sha or (db_commits[-1]["sha"] if db_commits else None)

    adapter_obj = adapter or RegexAdapter(regex_repo_dir=str(repo_dir))
    configured_benches = regressor._project_benchmarks(db, proj_id, project)
    if benchmarks_override:
        benchmarks = list(dict.fromkeys(benchmarks_override))
    elif configured_benches:
        benchmarks = list(configured_benches)
    else:
        benchmarks = adapter_obj.list_benchmarks()

    discovered = discover_new_commits(
        repo_dir,
        anchor_sha,
        remote=remote,
        branch=branch,
        fetch=fetch,
        max_commits=max_commits,
    )

    cpu_model = regressor._env_info()["cpu"]
    rustc_ver = _rustc_version_string()
    collected_entries: List[Dict[str, Any]] = []
    skipped = 0
    profiled = 0
    build_failed = 0

    def _upsert_commit(
        item: Dict[str, str],
        *,
        build_ok: bool,
        build_seconds: float,
        started_utc: str,
        finished_utc: str = "",
    ) -> int:
        return db.insert_commit(
            project_id=proj_id,
            sha=item["sha"],
            short_sha=item["short_sha"],
            author_date=item["author_date"],
            subject=item["subject"],
            build_ok=build_ok,
            build_seconds=build_seconds,
            cpu_model=cpu_model,
            rustc_version=rustc_ver,
            run_started_utc=started_utc,
            run_finished_utc=finished_utc,
        )

    for item in discovered:
        sha = item["sha"]
        if sha in known_shas:
            skipped += 1
            continue

        started_utc = datetime.now(timezone.utc).isoformat()
        canary_pre = CanaryBenchmark.run_reps(reps=canary_reps) if canary_reps > 0 else None
        br = adapter_obj.build(sha, workdir=workdir)

        if not br.ok:
            _upsert_commit(
                item,
                build_ok=False,
                build_seconds=br.seconds,
                started_utc=started_utc,
                finished_utc=datetime.now(timezone.utc).isoformat(),
            )
            if cleanup_worktrees:
                _cleanup_commit_worktree(repo_dir, workdir, sha)
            build_failed += 1
            collected_entries.append({
                **item,
                "build_ok": False,
                "build_seconds": br.seconds,
                "canary_status": "NOT_RECORDED",
                "log_tail": br.log_tail,
            })
            known_shas.add(sha)
            continue

        cid = _upsert_commit(item, build_ok=True, build_seconds=br.seconds, started_utc=started_utc)

        bulk_rows = []
        for bench in benchmarks:
            for rep_idx in range(1, reps + 1):
                samples = adapter_obj.run(
                    bench,
                    iters=iters,
                    warmup=warmup,
                    inject_ns=0,
                    artifact=br.artifact,
                )
                med = float(np.median(samples))
                bulk_rows.append((cid, bench, rep_idx, "", med))
        db.insert_runs_bulk(bulk_rows)

        _upsert_commit(
            item,
            build_ok=True,
            build_seconds=br.seconds,
            started_utc=started_utc,
            finished_utc=datetime.now(timezone.utc).isoformat(),
        )

        canary_status = "NOT_RECORDED"
        if canary_pre is not None:
            drift = CanaryBenchmark.evaluate_drift(canary_pre, CanaryBenchmark.run_reps(reps=canary_reps))
            canary_status = drift["status"]

        if cleanup_worktrees:
            _cleanup_commit_worktree(repo_dir, workdir, sha)

        profiled += 1
        known_shas.add(sha)
        collected_entries.append({
            **item,
            "build_ok": True,
            "build_seconds": br.seconds,
            "canary_status": canary_status,
        })

    all_commits = db.get_project_commits(proj_id)
    if len(all_commits) >= 2:
        regressor.cmd_batch(
            argparse.Namespace(
                db=str(db_path),
                project=project,
                rolling_window=1,
                adjust_autocorr=False,
                fdr=fdr,
                verify_legacy=False,
            )
        )

    comparisons = [dict(r) for r in db.get_project_comparisons(proj_id)]
    flagged = [c for c in comparisons if c["verdict"] == "flag" and c["fdr_significant"]]

    changepoints: List[Dict[str, Any]] = []
    if len(all_commits) >= 6:
        shas_all = [c["short_sha"] for c in all_commits]
        known_breaks = find_session_break_indices(all_commits)
        nf_mult = regressor._project_noise_floor_multiplier(project)
        runs_by = db.get_project_runs(proj_id)
        for bench in benchmarks:
            series = [runs_by.get((c["id"], bench), []) for c in all_commits]
            if all(len(r) >= 1 for r in series):
                for cp in detect_series_changepoints_edivisive(
                    shas_all,
                    series,
                    significance_alpha=0.05,
                    known_breaks=known_breaks,
                    noise_floor_multiplier=nf_mult,
                ):
                    changepoints.append({"benchmark": bench, **cp})

    resolved_out = out_dataset
    if resolved_out is None:
        resolved_out = root_dir / "data" / f"{project}_continuous_history.json.gz"
    elif not resolved_out.is_absolute():
        resolved_out = root_dir / resolved_out

    if len(all_commits) >= 1:
        regressor.cmd_export_data(
            argparse.Namespace(db=str(db_path), project=project, out=str(resolved_out))
        )

    summary = {
        "project": project,
        "source_dataset": str(source_dataset) if source_dataset else None,
        "out_dataset": str(resolved_out),
        "db_path": str(db_path),
        "since_sha": anchor_sha,
        "platform": platform.platform(),
        "rustc_version": rustc_ver,
        "benchmarks": benchmarks,
        "fdr": fdr,
        "commits_discovered": len(discovered),
        "commits_profiled": profiled,
        "commits_skipped": skipped,
        "commits_build_failed": build_failed,
        "total_commits": len(all_commits),
        "total_comparisons": len(comparisons),
        "post_fdr_flags": len(flagged),
        "collected": collected_entries,
        "flagged": [
            {
                "benchmark": f["benchmark"],
                "base_sha": f["base_sha"],
                "cand_sha": f["cand_sha"],
                "shift_pct": f["shift_pct"],
                "p_value": f["p_value"],
                "session_gap_min": f["session_gap_min"],
            }
            for f in flagged
        ],
        "changepoints": changepoints,
    }

    if summary_json is not None:
        sj = summary_json if summary_json.is_absolute() else (root_dir / summary_json)
        sj.parent.mkdir(parents=True, exist_ok=True)
        sj.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if summary_md is not None:
        sm = summary_md if summary_md.is_absolute() else (root_dir / summary_md)
        sm.parent.mkdir(parents=True, exist_ok=True)
        sm.write_text(_render_summary_markdown(summary), encoding="utf-8")

    return summary


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Fetch new upstream commits since the last recorded dataset entry, benchmark, and detect regressions."
    )
    p.add_argument("--project", default="regex", help="Registered project name (default: %(default)s)")
    p.add_argument(
        "--dataset",
        default="auto",
        help="Baseline .json.gz archive path or 'auto' (default: %(default)s)",
    )
    p.add_argument("--out-dataset", type=Path, help="Output .json.gz archive path")
    p.add_argument(
        "--db",
        type=Path,
        default=Path("noise-bench/results/continuous.db"),
        help="SQLite DB path (default: %(default)s)",
    )
    p.add_argument("--repo", type=Path, default=Path("regex"), help="Target git repo directory (default: %(default)s)")
    p.add_argument("--remote", default="origin", help="Git remote to fetch from (default: %(default)s)")
    p.add_argument("--branch", default="master", help="Upstream branch to track (default: %(default)s)")
    p.add_argument("--since-sha", help="Override baseline commit SHA instead of reading from dataset")
    p.add_argument("--no-fetch", action="store_true", help="Do not run git fetch (use local HEAD; useful offline)")
    p.add_argument(
        "--max-commits",
        type=regressor.non_negative_int,
        default=0,
        help="Optional cap on new commits per invocation (0 = all new commits)",
    )
    p.add_argument("--benchmark", action="append", help="Benchmark name filter (repeatable; default: all configured)")
    p.add_argument("--reps", type=regressor.positive_int, default=15, help="Repetitions per commit (default: %(default)s)")
    p.add_argument("--iters", type=regressor.positive_int, default=1500, help="Iterations per rep (default: %(default)s)")
    p.add_argument("--warmup", type=regressor.non_negative_int, default=150, help="Warmup iterations (default: %(default)s)")
    p.add_argument(
        "--canary-reps",
        type=regressor.non_negative_int,
        default=5,
        help="Canary repetitions per commit, 0 disables (default: %(default)s)",
    )
    p.add_argument("--fdr", choices=("bh", "by"), default="by", help="FDR method (default: %(default)s)")
    p.add_argument("--workdir", type=Path, default=Path(".regressor-builds"), help="Isolated worktree build root")
    p.add_argument("--keep-worktrees", action="store_true", help="Retain isolated worktrees after benchmarking")
    p.add_argument("--summary-json", type=Path, help="Optional JSON summary output path")
    p.add_argument("--summary-md", type=Path, help="Optional Markdown summary output path")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    summary = run_continuous_collection(
        project=args.project,
        dataset_arg=args.dataset,
        out_dataset=args.out_dataset,
        db_path=args.db,
        repo_dir=args.repo,
        remote=args.remote,
        branch=args.branch,
        since_sha=args.since_sha,
        fetch=not args.no_fetch,
        max_commits=args.max_commits,
        benchmarks_override=args.benchmark,
        reps=args.reps,
        iters=args.iters,
        warmup=args.warmup,
        canary_reps=args.canary_reps,
        fdr=args.fdr,
        workdir=args.workdir,
        cleanup_worktrees=not args.keep_worktrees,
        summary_json=args.summary_json,
        summary_md=args.summary_md,
    )
    print(
        f"[continuous] discovered={summary['commits_discovered']} "
        f"profiled={summary['commits_profiled']} "
        f"failed={summary['commits_build_failed']} "
        f"post_fdr_flags={summary['post_fdr_flags']} "
        f"out={summary['out_dataset']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
