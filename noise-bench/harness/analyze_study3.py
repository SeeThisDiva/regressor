#!/usr/bin/env python3
"""
Phase C analysis and export driver for Study 3.

Executes `regressor.py batch regex --fdr by`, E-Divisive `changepoint` per
benchmark, three-way `evaluate-power` calibration, exports
`data/regex_study3_history.json.gz`, and writes `noise-bench/results/study3_analysis.json`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

HARNESS_DIR = Path(__file__).resolve().parent
NOISE_BENCH_DIR = HARNESS_DIR.parent
REPO_ROOT = NOISE_BENCH_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.db import Database  # noqa: E402
from core.detector import bh_fdr_correct, compare_distributions  # noqa: E402
from core.power import aa_contiguous_split, aa_random_split, evaluate_power_curve, load_session_medians, null_transition_fpr  # noqa: E402
from core.series_detector import detect_series_changepoints_edivisive  # noqa: E402
from core.session import find_session_break_indices, is_session_break, session_gap_minutes  # noqa: E402


def _sanitize_cli_output(text: str) -> str:
    root_win = str(REPO_ROOT.resolve())
    root_posix = REPO_ROOT.resolve().as_posix()
    return text.replace(root_win + "\\", "").replace(root_posix + "/", "").replace(root_win, ".").replace(root_posix, ".")


def _run_cli(args: List[str]) -> str:
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "regressor.py"), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=600,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"regressor.py {' '.join(args)} failed (rc={proc.returncode}):\n{proc.stderr}\n{proc.stdout}")
    return _sanitize_cli_output(proc.stdout)


def _load_commit_metas(results_dir: Path) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not results_dir.exists():
        return out
    for cdir in sorted(results_dir.iterdir()):
        mp = cdir / "meta.json"
        if cdir.is_dir() and mp.exists():
            try:
                data = json.loads(mp.read_text(encoding="utf-8"))
                if "commit_sha" in data:
                    out[data["commit_sha"]] = data
            except (OSError, json.JSONDecodeError):
                continue
    return out


def analyze_study3(
    db_path: Path,
    commits_manifest_path: Path,
    results_dir: Path,
    baseline_dir: Optional[Path],
    export_gz_path: Path,
    output_json_path: Path,
) -> Dict[str, Any]:
    """Run all Phase C analyses and export portable Study 3 artifacts."""
    # 1. Execute authoritative CLI commands: batch (--fdr by) and export-data.
    batch_stdout = _run_cli(["--db", str(db_path), "batch", "regex", "--fdr", "by"])
    export_stdout = _run_cli(["--db", str(db_path), "export-data", "regex", "--out", str(export_gz_path)])

    db = Database(str(db_path))
    proj_id = db.get_project_id("regex")
    if proj_id is None:
        raise RuntimeError(f"Project 'regex' not found in {db_path}")

    commits = db.get_project_commits(proj_id)
    benches = db.get_project_benchmarks(proj_id)
    runs_by = db.get_project_runs(proj_id)

    # Verify CLI `changepoint` works on every benchmark that has complete runs.
    for bench in benches:
        if len(commits) >= 6 and all(len(runs_by.get((c["id"], bench), [])) >= 1 for c in commits):
            _run_cli(["--db", str(db_path), "changepoint", "regex", "--benchmark", bench])

    # Load static manifest and per-commit meta.json (canary + classification).
    manifest_by_sha: Dict[str, Dict[str, Any]] = {}
    if commits_manifest_path.exists():
        raw_manifest = json.loads(commits_manifest_path.read_text(encoding="utf-8"))
        for c in raw_manifest.get("commits", []):
            manifest_by_sha[c["sha"]] = c
    commit_metas = _load_commit_metas(results_dir)

    commit_records: List[Dict[str, Any]] = []
    for c in commits:
        sha = c["sha"]
        m_extra = manifest_by_sha.get(sha, {})
        r_meta = commit_metas.get(sha, {})
        canary = r_meta.get("canary") or {}
        within_c = canary.get("within_commit") or {}
        prev_c = canary.get("vs_prev_commit") or {}
        commit_records.append({
            "sha": sha,
            "short_sha": c["short_sha"],
            "short7": sha[:7],
            "author_date": c["author_date"],
            "subject": c["subject"],
            "build_ok": bool(c["build_ok"]),
            "build_seconds": c["build_seconds"],
            "run_started_utc": c["run_started_utc"],
            "run_finished_utc": c["run_finished_utc"],
            "touches_src": bool(m_extra.get("touches_src", r_meta.get("touches_src", False))),
            "is_doc_or_comment_only": bool(
                m_extra.get("is_doc_or_comment_only", r_meta.get("is_doc_or_comment_only", False))
            ),
            "is_null_control": bool(m_extra.get("is_null_control", r_meta.get("is_null_control", False))),
            "diff_classification": m_extra.get("diff_classification", r_meta.get("diff_classification", "")),
            "canary_within_status": within_c.get("status", "NOT_RECORDED"),
            "canary_within_shift_pct": within_c.get("shift_pct"),
            "canary_vs_prev_status": prev_c.get("status", "ANCHOR" if not prev_c else "NOT_RECORDED"),
            "canary_vs_prev_shift_pct": prev_c.get("shift_pct"),
        })

    # Recompute pairwise comparisons cleanly to preserve both BH and BY FDR + autocorr diagnostics.
    comparisons: List[Dict[str, Any]] = []
    commit_rec_by_sha = {r["sha"]: r for r in commit_records}
    for i in range(1, len(commits)):
        base_c = commits[i - 1]
        cand_c = commits[i]
        gap_min = session_gap_minutes(base_c, cand_c)
        cand_rec = commit_rec_by_sha[cand_c["sha"]]

        for bench in benches:
            base_runs = runs_by.get((base_c["id"], bench), [])
            cand_runs = runs_by.get((cand_c["id"], bench), [])
            if len(base_runs) < 5 or len(cand_runs) < 5:
                continue
            res = compare_distributions(
                np.asarray(base_runs, dtype=np.float64),
                np.asarray(cand_runs, dtype=np.float64),
                alpha=0.01,
                noise_floor_multiplier=3.0,
                adjust_autocorr=False,
            )
            autocorr_res = compare_distributions(
                np.asarray(base_runs, dtype=np.float64),
                np.asarray(cand_runs, dtype=np.float64),
                alpha=0.01,
                noise_floor_multiplier=3.0,
                adjust_autocorr=True,
            )
            res.update({
                "block_bootstrap_p_value": autocorr_res["block_bootstrap_p_value"],
                "autocorr_adjusted_p_value": autocorr_res["p_value"],
                "autocorr_verdict": autocorr_res["verdict"],
                "base_commit_id": base_c["id"],
                "cand_commit_id": cand_c["id"],
                "base_sha": base_c["short7"] if "short7" in base_c.keys() else base_c["sha"][:7],
                "cand_sha": cand_c["sha"][:7],
                "base_full_sha": base_c["sha"],
                "cand_full_sha": cand_c["sha"],
                "cand_subject": cand_c["subject"],
                "benchmark": bench,
                "session_gap_min": gap_min,
                "session_break": bool(is_session_break(gap_min)),
                "cand_is_doc_or_comment_only": cand_rec["is_doc_or_comment_only"],
                "cand_is_null_control": cand_rec["is_null_control"],
                "cand_canary_within_status": cand_rec["canary_within_status"],
                "cand_canary_vs_prev_status": cand_rec["canary_vs_prev_status"],
            })
            comparisons.append(res)

    bh_list = [dict(c) for c in comparisons]
    bh_fdr_correct(bh_list, alpha=0.05, method="bh")
    bh_fdr_correct(comparisons, alpha=0.05, method="by")
    for idx, comp in enumerate(comparisons):
        comp["by_fdr_significant"] = bool(comp["fdr_significant"])
        comp["bh_fdr_significant"] = bool(bh_list[idx]["fdr_significant"])

    # Series E-Divisive changepoints per benchmark (filtering to commits with recorded runs).
    known_breaks = find_session_break_indices(commits)
    edivisive: Dict[str, List[Dict[str, Any]]] = {}
    for bench in benches:
        valid_pairs = [
            (idx, c["short_sha"], runs_by.get((c["id"], bench), []))
            for idx, c in enumerate(commits)
            if runs_by.get((c["id"], bench), [])
        ]
        if len(valid_pairs) >= 6:
            valid_shas = [p[1] for p in valid_pairs]
            valid_runs = [p[2] for p in valid_pairs]
            valid_breaks = [pos for pos, (orig_idx, _, _) in enumerate(valid_pairs) if orig_idx in known_breaks]
            edivisive[bench] = detect_series_changepoints_edivisive(
                valid_shas,
                valid_runs,
                significance_alpha=0.05,
                known_breaks=valid_breaks,
                noise_floor_multiplier=3.0,
            )

    # Power & 3-way FPR evaluation.
    power_summary: Dict[str, Any] = {
        "tier3_null_subject": null_transition_fpr(comparisons),
        "tier3_all_null_controls": {
            "n": sum(1 for c in comparisons if c["cand_is_null_control"]),
            "flags_by_fdr": sum(
                1 for c in comparisons if c["cand_is_null_control"] and c["verdict"] == "flag" and c["by_fdr_significant"]
            ),
            "flags_bh_fdr": sum(
                1 for c in comparisons if c["cand_is_null_control"] and c["verdict"] == "flag" and c["bh_fdr_significant"]
            ),
        },
        "session_baseline": {},
    }
    if baseline_dir and baseline_dir.exists():
        session = load_session_medians(baseline_dir, benches)
        if session:
            # Verify CLI evaluate-power runs cleanly on the first benchmark.
            first_bench = next(iter(session))
            power_stdout = _run_cli([
                "--db",
                str(db_path),
                "evaluate-power",
                "regex",
                "--session-dir",
                str(baseline_dir),
                "--benchmark",
                first_bench,
            ])
            power_summary["cli_sample_output"] = power_stdout
            for bench, meds in session.items():
                power_summary["session_baseline"][bench] = {
                    "n_reps": len(meds),
                    "aa_random_split": aa_random_split(meds, trials=1000),
                    "aa_contiguous_split": aa_contiguous_split(meds),
                    "power_curve": evaluate_power_curve(meds, trials_per_point=300),
                }

    flagged_by = [c for c in comparisons if c["verdict"] == "flag" and c["by_fdr_significant"]]
    flagged_bh = [c for c in comparisons if c["verdict"] == "flag" and c["bh_fdr_significant"]]
    flagged_pre = [c for c in comparisons if c["verdict"] == "flag"]

    flagged_list = [
        {
            "base_sha": c["base_sha"],
            "cand_sha": c["cand_sha"],
            "cand_full_sha": c["cand_full_sha"],
            "cand_subject": c["cand_subject"],
            "benchmark": c["benchmark"],
            "shift_pct": c["shift_pct"],
            "p_value": c["p_value"],
            "baseline_cv_pct": c["baseline_cv_pct"],
            "noise_floor_pct": c["noise_floor_pct"],
            "by_fdr_significant": c["by_fdr_significant"],
            "bh_fdr_significant": c["bh_fdr_significant"],
            "session_break": c["session_break"],
            "cand_is_null_control": c["cand_is_null_control"],
            "cand_canary_within_status": c["cand_canary_within_status"],
            "cand_canary_vs_prev_status": c["cand_canary_vs_prev_status"],
        }
        for c in flagged_by
    ]

    # Per-benchmark CV distribution across commits.
    per_bench_cv: Dict[str, Dict[str, float]] = {}
    for bench in benches:
        cvs = []
        medians = []
        for c in commits:
            r = runs_by.get((c["id"], bench), [])
            if len(r) > 1:
                arr = np.asarray(r, dtype=np.float64)
                cvs.append(float(np.std(arr, ddof=1) / np.mean(arr) * 100.0))
                medians.append(float(np.median(arr)))
        if cvs:
            per_bench_cv[bench] = {
                "median_cv_pct": round(float(np.median(cvs)), 3),
                "max_cv_pct": round(float(np.max(cvs)), 3),
                "anchor_median_ns": round(float(medians[0]), 1),
                "head_median_ns": round(float(medians[-1]), 1),
            }

    analysis = {
        "study": "Study 3 (1-year rust-lang/regex master: 2025-11-07 to 3d79fe9)",
        "total_commits": len(commits),
        "total_benchmarks": len(benches),
        "benchmarks": benches,
        "total_comparisons": len(comparisons),
        "flagged_pre_fdr": len(flagged_pre),
        "flagged_post_bh_fdr": len(flagged_bh),
        "flagged_post_by_fdr": len(flagged_by),
        "doc_or_comment_only_comparisons": sum(1 for c in comparisons if c["cand_is_doc_or_comment_only"]),
        "doc_or_comment_only_flags": sum(
            1 for c in flagged_by if c["cand_is_doc_or_comment_only"]
        ),
        "null_control_comparisons": sum(1 for c in comparisons if c["cand_is_null_control"]),
        "null_control_flags_by_fdr": sum(1 for c in flagged_by if c["cand_is_null_control"]),
        "canary_within_suspect_commits": sum(
            1 for c in commit_records if c["canary_within_status"] == "ENVIRONMENT_SUSPECT"
        ),
        "canary_vs_prev_suspect_commits": sum(
            1 for c in commit_records if c["canary_vs_prev_status"] == "ENVIRONMENT_SUSPECT"
        ),
        "flagged_by_fdr": flagged_list,
        "per_benchmark_cv": per_bench_cv,
        "commits": commit_records,
        "comparisons": comparisons,
        "edivisive_changepoints": edivisive,
        "power_evaluation": power_summary,
        "cli_batch_stdout": batch_stdout,
        "cli_export_stdout": export_stdout,
    }

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")
    return analysis


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Analyze Study 3 SQLite DB and export results.")
    ap.add_argument("--db", default=str(NOISE_BENCH_DIR / "results" / "study3" / "study3.db"))
    ap.add_argument("--commits-meta", default=str(HARNESS_DIR / "commits_study3.json"))
    ap.add_argument("--results-dir", default=str(NOISE_BENCH_DIR / "results" / "study3_commits"))
    ap.add_argument("--baseline-dir", default=str(NOISE_BENCH_DIR / "results" / "study3_baseline"))
    ap.add_argument("--export-gz", default=str(REPO_ROOT / "data" / "regex_study3_history.json.gz"))
    ap.add_argument("--out", default=str(NOISE_BENCH_DIR / "results" / "study3_analysis.json"))
    args = ap.parse_args(argv)

    analysis = analyze_study3(
        db_path=Path(args.db),
        commits_manifest_path=Path(args.commits_meta),
        results_dir=Path(args.results_dir),
        baseline_dir=Path(args.baseline_dir) if args.baseline_dir else None,
        export_gz_path=Path(args.export_gz),
        output_json_path=Path(args.out),
    )
    print(
        f"[study3-analyze] commits={analysis['total_commits']} benches={analysis['total_benchmarks']} "
        f"comparisons={analysis['total_comparisons']} pre_fdr={analysis['flagged_pre_fdr']} "
        f"bh_fdr={analysis['flagged_post_bh_fdr']} by_fdr={analysis['flagged_post_by_fdr']}"
    )
    for f in analysis["flagged_by_fdr"]:
        print(
            f"  FLAG {f['cand_sha']} {f['benchmark']:34s} shift={f['shift_pct']:+.2f}% "
            f"p={f['p_value']:.2e} CV={f['baseline_cv_pct']:.2f}% floor={f['noise_floor_pct']:.2f}% "
            f"null={f['cand_is_null_control']} ({f['cand_subject']})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
