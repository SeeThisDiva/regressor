"""
core/layout_floor.py
Post-hoc offline calibration of per-benchmark LTO layout-shift noise floors
on Study 3 (`data/regex_study3_history.json.gz`), evaluated via disjoint 2-fold
cross-validation across null-control commits without touching published results.
"""

from __future__ import annotations

import contextlib
import gzip
import io
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

from adapters.base import BaseAdapter
from core.detector import bh_fdr_correct, compare_distributions, sample_cv
from core.models import BuildResult
from core.report import wilson_ci
from core.validation import validate_adapter_synthetic

CLOUDFLARE_SHA7 = "64ad0b6"
CLOUDFLARE_BENCH = "rebar_curated_06_cloudflare_redos_long"

# Null-control commit subjects (doc/comment/changelog, Cargo.toml version/deps bumps, CI/ignore/test-only).
NULL_CONTROL_SUBJECT_RE = re.compile(
    r"^(?:"
    r"(?:docs?|changelog|cargo|deps|github|ignore|tests?)(?:\([^)]*\))?:"
    r"|(?:\d+\.\d+\.\d+\b)"
    r"|(?:(?:regex(?:-(?:lite|syntax|automata))?|rure)-\d+\.\d+\.\d+\b)"
    r"|automata:\s+disable miri on a couple doc tests$"
    r")",
    re.IGNORECASE,
)


def is_null_control_subject(subject: str) -> bool:
    """Return True when ``subject`` identifies a null-control commit in Study 3."""
    return bool(NULL_CONTROL_SUBJECT_RE.match((subject or "").strip()))


class _ReplayBenchAdapter(BaseAdapter):
    """Deterministic offline adapter replaying one benchmark's Study 3 median and CV."""

    def __init__(self, bench_name: str, median_ns: float, cv_fraction: float, seed: int) -> None:
        self._bench_name = bench_name
        self._median_ns = float(median_ns)
        self._cv_fraction = float(cv_fraction)
        self._rng = np.random.default_rng(seed)

    def list_benchmarks(self) -> List[str]:
        return [self._bench_name]

    def build(self, commit_ref: str, workdir: Optional[Path] = None) -> BuildResult:
        return BuildResult(ok=True, seconds=0.0, artifact=commit_ref)

    def run(
        self,
        bench_name: str,
        iters: int,
        warmup: int,
        inject_ns: int = 0,
        artifact: Optional[str] = None,
    ) -> List[float]:
        sample = float(self._rng.normal(self._median_ns, self._cv_fraction * self._median_ns))
        return [max(1.0, sample + float(inject_ns))]


def _load_study3_archive(archive_path: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    with gzip.open(archive_path, "rt", encoding="utf-8") as fh:
        blob = json.load(fh)
    commits = blob.get("commits") or []
    benchmarks = sorted({bench for c in commits for bench in (c.get("runs") or {})})
    return commits, benchmarks


def _load_triage_map(triage_path: Optional[Path]) -> Dict[Tuple[str, str], str]:
    if triage_path is None or not triage_path.is_file():
        return {}
    entries = json.loads(triage_path.read_text(encoding="utf-8"))
    return {
        (str(item["benchmark"]), str(item["commit"])[:7]): str(item["status"])
        for item in entries
        if item.get("benchmark") and item.get("commit") and item.get("status")
    }


def estimate_layout_floors(
    transitions: Sequence[Dict[str, Any]],
    calibration_indices: Set[int],
    *,
    multiplier: float = 3.0,
) -> Dict[str, float]:
    """Estimate per-benchmark ``multiplier * std(shift_pct, ddof=1)`` on calibration commits."""
    by_bench: Dict[str, List[float]] = {}
    for row in transitions:
        if row["commit_index"] in calibration_indices:
            by_bench.setdefault(row["benchmark"], []).append(float(row["shift_pct"]))

    floors: Dict[str, float] = {}
    for bench, shifts in by_bench.items():
        if len(shifts) <= 1:
            floors[bench] = 0.0
        else:
            floors[bench] = round(float(multiplier * np.std(np.asarray(shifts, dtype=np.float64), ddof=1)), 4)
    return floors


def _evaluate_commit_subset(
    commits: Sequence[Dict[str, Any]],
    benchmarks: Sequence[str],
    eval_indices: Set[int],
    null_indices: Set[int],
    *,
    floors: Optional[Dict[str, float]],
    alpha: float,
    multiplier: float,
    fdr_alpha: float,
    fdr_method: str,
    triage_map: Dict[Tuple[str, str], str],
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for idx in sorted(eval_indices):
        base_c = commits[idx - 1]
        cand_c = commits[idx]
        cand_sha7 = str(cand_c["short_sha"])[:7]
        is_null = idx in null_indices
        for bench in benchmarks:
            min_floor = float(floors.get(bench, 0.0)) if floors is not None else 0.0
            res = compare_distributions(
                np.asarray(base_c["runs"][bench], dtype=np.float64),
                np.asarray(cand_c["runs"][bench], dtype=np.float64),
                alpha=alpha,
                noise_floor_multiplier=multiplier,
                min_noise_floor_pct=min_floor,
            )
            res.update({
                "commit_index": idx,
                "cand_sha7": cand_sha7,
                "benchmark": bench,
                "is_null_control": is_null,
            })
            rows.append(res)

    bh_fdr_correct(rows, alpha=fdr_alpha, method=fdr_method)
    flagged = [r for r in rows if r["verdict"] == "flag" and r["fdr_significant"]]
    null_rows = [r for r in rows if r["is_null_control"]]
    null_flags = [r for r in flagged if r["is_null_control"]]

    confirmed = sum(1 for r in flagged if triage_map.get((r["benchmark"], r["cand_sha7"])) == "confirmed")
    false_pos = sum(1 for r in flagged if triage_map.get((r["benchmark"], r["cand_sha7"])) == "false_positive")
    layout_art = sum(1 for r in flagged if triage_map.get((r["benchmark"], r["cand_sha7"])) == "layout_artifact")

    c64 = next(
        (r for r in rows if r["cand_sha7"] == CLOUDFLARE_SHA7 and r["benchmark"] == CLOUDFLARE_BENCH),
        None,
    )
    c64_flagged = bool(c64 and c64["verdict"] == "flag" and c64["fdr_significant"])

    n_null = len(null_rows)
    k_null = len(null_flags)
    n_flag = len(flagged)
    return {
        "comparisons": len(rows),
        "flags": n_flag,
        "heldout_null_comparisons": n_null,
        "heldout_null_flags": k_null,
        "heldout_null_fpr_pct": round(100.0 * k_null / n_null, 2) if n_null else 0.0,
        "heldout_null_wilson_ci95_pct": wilson_ci(k_null, n_null),
        "triaged_confirmed": confirmed,
        "triaged_false_positive": false_pos,
        "triaged_layout_artifact": layout_art,
        "triaged_fp_rate_pct": round(100.0 * false_pos / n_flag, 2) if n_flag else None,
        "triaged_fp_wilson_ci95_pct": wilson_ci(false_pos, n_flag),
        "cloudflare_64ad0b6_flagged": c64_flagged,
        "cloudflare_64ad0b6_shift_pct": c64["shift_pct"] if c64 else None,
        "cloudflare_64ad0b6_floor_pct": round(float(c64["noise_floor_pct"]), 3) if c64 else None,
    }


def _evaluate_validation_gate_detection(
    commits: Sequence[Dict[str, Any]],
    benchmarks: Sequence[str],
    floors: Dict[str, float],
    *,
    base_seed: int = 1000,
) -> Dict[str, int]:
    before_hits = 0
    after_hits = 0
    for b_idx, bench in enumerate(benchmarks):
        med_ns = float(np.median([np.median(c["runs"][bench]) for c in commits]))
        med_cv = float(np.median([sample_cv(c["runs"][bench]) for c in commits]))

        with contextlib.redirect_stdout(io.StringIO()):
            res_before = validate_adapter_synthetic(
                _ReplayBenchAdapter(bench, med_ns, med_cv, seed=base_seed + b_idx),
                bench,
                reps=25,
                min_noise_floor_pct=0.0,
            )
            res_after = validate_adapter_synthetic(
                _ReplayBenchAdapter(bench, med_ns, med_cv, seed=base_seed + b_idx),
                bench,
                reps=25,
                min_noise_floor_pct=floors.get(bench, 0.0),
            )
        if res_before.large_injection_flagged:
            before_hits += 1
        if res_after.large_injection_flagged:
            after_hits += 1
    return {"total_benchmarks": len(benchmarks), "before": before_hits, "after": after_hits}


def _evaluate_heldout_injections(
    commits: Sequence[Dict[str, Any]],
    benchmarks: Sequence[str],
    folds: Sequence[Tuple[Set[int], Dict[str, float]]],
    effect_sizes_pct: Sequence[float],
    *,
    alpha: float,
    multiplier: float,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for eff in effect_sizes_pct:
        scale = 1.0 + eff / 100.0
        total = 0
        before_hits = 0
        after_hits = 0
        for eval_null_indices, floors in folds:
            for idx in sorted(eval_null_indices):
                base_runs_map = commits[idx - 1]["runs"]
                cand_runs_map = commits[idx]["runs"]
                for bench in benchmarks:
                    base_arr = np.asarray(base_runs_map[bench], dtype=np.float64)
                    cand_arr = np.asarray(cand_runs_map[bench], dtype=np.float64) * scale
                    r_before = compare_distributions(
                        base_arr,
                        cand_arr,
                        alpha=alpha,
                        noise_floor_multiplier=multiplier,
                        min_noise_floor_pct=0.0,
                    )
                    total += 1
                    if r_before["verdict"] == "flag":
                        before_hits += 1
                    eff_floor = max(float(r_before["noise_floor_pct"]), float(floors.get(bench, 0.0)))
                    if r_before["statistically_significant"] and abs(float(r_before["shift_pct"])) > eff_floor:
                        after_hits += 1
        rows.append({
            "effect_pct": float(eff),
            "total": total,
            "before_detected": before_hits,
            "before_pct": round(100.0 * before_hits / total, 1) if total else 0.0,
            "after_detected": after_hits,
            "after_pct": round(100.0 * after_hits / total, 1) if total else 0.0,
        })
    return rows


def evaluate_study3_layout_floor(
    archive_path: Path,
    *,
    seed: int = 42,
    multiplier: float = 3.0,
    alpha: float = 0.01,
    fdr_alpha: float = 0.05,
    fdr_method: str = "by",
    effect_sizes_pct: Sequence[float] = (5.0, 8.0, 10.0, 15.0, 20.0, 50.0, 95.0),
    triage_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run disjoint 2-fold offline layout-floor calibration on Study 3."""
    commits, benchmarks = _load_study3_archive(archive_path)
    triage_map = _load_triage_map(triage_path)

    all_indices = set(range(1, len(commits)))
    null_indices = {
        idx
        for idx in all_indices
        if is_null_control_subject(str(commits[idx].get("subject", "")))
    }

    # Precompute all raw pairwise comparisons once so calibration extracts signed shifts cleanly.
    raw_transitions: List[Dict[str, Any]] = []
    for idx in sorted(all_indices):
        base_c = commits[idx - 1]
        cand_c = commits[idx]
        for bench in benchmarks:
            res = compare_distributions(
                np.asarray(base_c["runs"][bench], dtype=np.float64),
                np.asarray(cand_c["runs"][bench], dtype=np.float64),
                alpha=alpha,
                noise_floor_multiplier=multiplier,
            )
            raw_transitions.append({
                "commit_index": idx,
                "benchmark": bench,
                "shift_pct": res["shift_pct"],
            })

    rng = np.random.default_rng(seed)
    perm = rng.permutation(sorted(null_indices))
    half = len(perm) // 2
    split_a = set(int(x) for x in perm[:half])
    split_b = set(int(x) for x in perm[half:])

    fold_specs = (
        ("fold_a", split_a, split_b),
        ("fold_b", split_b, split_a),
    )

    folds_out: Dict[str, Any] = {}
    inj_fold_inputs: List[Tuple[Set[int], Dict[str, float]]] = []
    for fold_name, cal_nulls, eval_nulls in fold_specs:
        eval_indices = (all_indices - null_indices) | eval_nulls
        assert not (cal_nulls & eval_indices), "Calibration and evaluation commits must be disjoint"

        floors = estimate_layout_floors(raw_transitions, cal_nulls, multiplier=multiplier)
        inj_fold_inputs.append((eval_nulls, floors))

        before_eval = _evaluate_commit_subset(
            commits,
            benchmarks,
            eval_indices,
            null_indices,
            floors=None,
            alpha=alpha,
            multiplier=multiplier,
            fdr_alpha=fdr_alpha,
            fdr_method=fdr_method,
            triage_map=triage_map,
        )
        after_eval = _evaluate_commit_subset(
            commits,
            benchmarks,
            eval_indices,
            null_indices,
            floors=floors,
            alpha=alpha,
            multiplier=multiplier,
            fdr_alpha=fdr_alpha,
            fdr_method=fdr_method,
            triage_map=triage_map,
        )
        val_gate = _evaluate_validation_gate_detection(commits, benchmarks, floors)
        folds_out[fold_name] = {
            "cal_null_indices": sorted(cal_nulls),
            "eval_null_indices": sorted(eval_nulls),
            "eval_indices": sorted(eval_indices),
            "cal_null_commits": len(cal_nulls),
            "eval_null_commits": len(eval_nulls),
            "calibrated_floors_pct": floors,
            "before": before_eval,
            "after": after_eval,
            "validation_8pct": val_gate,
        }

    full_baseline = _evaluate_commit_subset(
        commits,
        benchmarks,
        all_indices,
        null_indices,
        floors=None,
        alpha=alpha,
        multiplier=multiplier,
        fdr_alpha=fdr_alpha,
        fdr_method=fdr_method,
        triage_map=triage_map,
    )

    oof_total = sum(folds_out[f]["after"]["heldout_null_comparisons"] for f in ("fold_a", "fold_b"))
    oof_before_k = sum(folds_out[f]["before"]["heldout_null_flags"] for f in ("fold_a", "fold_b"))
    oof_after_k = sum(folds_out[f]["after"]["heldout_null_flags"] for f in ("fold_a", "fold_b"))

    injection_curve = _evaluate_heldout_injections(
        commits,
        benchmarks,
        inj_fold_inputs,
        effect_sizes_pct,
        alpha=alpha,
        multiplier=multiplier,
    )

    return {
        "seed": seed,
        "multiplier": multiplier,
        "total_commits": len(commits),
        "total_transitions": len(all_indices),
        "null_control_commits": len(null_indices),
        "non_null_commits": len(all_indices - null_indices),
        "benchmarks": list(benchmarks),
        "full_baseline": full_baseline,
        "folds": folds_out,
        "oof_heldout_nulls": {
            "comparisons": oof_total,
            "before_flags": oof_before_k,
            "before_fpr_pct": round(100.0 * oof_before_k / oof_total, 2) if oof_total else 0.0,
            "before_wilson_ci95_pct": wilson_ci(oof_before_k, oof_total),
            "after_flags": oof_after_k,
            "after_fpr_pct": round(100.0 * oof_after_k / oof_total, 2) if oof_total else 0.0,
            "after_wilson_ci95_pct": wilson_ci(oof_after_k, oof_total),
        },
        "heldout_injections": injection_curve,
    }
