"""
server/app.py
FastAPI backend for the regressor dashboard and JSON API.

`create_app(db_path)` returns an independent FastAPI instance bound to one SQLite
database file, keeping tests and multiple server instances isolated. For
`uvicorn server.app:app`, module-level `__getattr__` lazily builds the default
app from `REGRESSOR_DB` (default: `./regressor.db` at the repo root) so importing
this module has no filesystem side effects.
"""

import gzip
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Dict, List, Mapping, Optional, Tuple

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from scipy import stats

from core.db import MIN_SHA_PREFIX, Database, resolve_commit_pair, resolve_commit_prefix
from core.detector import bh_fdr_correct, compare_benchmark_runs, compare_distributions, sample_cv, summarize_distribution
from core.report import (
    compute_summary_from_records,
    discover_flamegraphs,
    load_project_noise_floor_multiplier,
    load_triage_entries,
    match_commit_flamegraphs,
    match_triage_entry,
    sanitize_issue_url,
    validate_project_name,
)
from core.session import SESSION_BREAK_MIN, commit_session_gaps, is_session_break, session_gap_minutes

ROOT_DIR = Path(__file__).parent.parent.resolve()
MAX_SHA_PREFIX = 64
MAX_PROJECT_LEN = 64
MAX_STUDY_LEN = 64
MIN_COMPARE_RUNS = 3
HISTOGRAM_BINS = 10
_KNOWN_STUDY_META = {
    "regex_history.json.gz": ("study1", "Study 1 · Aug 2025–Jan 2026 (cf00423..4733e28)", "bh"),
    "regex_study2_history.json.gz": ("study2", "Study 2 · Jan–Nov 2026 (4733e28..3d79fe9)", "bh"),
    "regex_study3_history.json.gz": ("study3", "Study 3 · Full Year (rebar suite)", "by"),
}
_SAFE_STUDY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

CSP_POLICY = (
    "default-src 'self'; "
    # Chart.js is vendored in ui/vendor/ (served from /static), so no third-party script origin.
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-src 'self'; "
    "frame-ancestors 'self'; "
    "object-src 'none'; "
    "base-uri 'self'"
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Content-Security-Policy": CSP_POLICY,
}

OPENAPI_TAGS = [
    {"name": "ui", "description": "Embedded laboratory dashboard HTML view."},
    {"name": "projects", "description": "Registered projects, benchmark time-series, and comparison logs."},
    {"name": "commits", "description": "Per-commit sampling distributions, histograms, and session context."},
    {"name": "compare", "description": "Ad-hoc non-parametric comparison between any two commits."},
]


class CompareRequest(BaseModel):
    """Payload for `POST /api/compare` (extra unexpected fields are rejected)."""

    model_config = ConfigDict(extra="forbid")
    project: str = Field(default="regex", description="Registered project name.")
    base_sha: str = Field(..., description="Baseline commit SHA or unique prefix (4-64 chars).")
    cand_sha: str = Field(..., description="Candidate commit SHA or unique prefix (4-64 chars).")
    study: Optional[str] = Field(default=None, description="Optional study dataset identifier (e.g. 'study1', 'study2', 'study3').")


def _validate_project_name(project: Optional[str]) -> None:
    if not project or len(project) > MAX_PROJECT_LEN:
        raise HTTPException(status_code=400, detail="Invalid project parameter")
    try:
        validate_project_name(project)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid project parameter") from exc


def _validate_study_param(study: Optional[str]) -> Optional[str]:
    if study is None or study == "" or study == "db":
        return None
    if len(study) > MAX_STUDY_LEN or not _SAFE_STUDY_RE.match(study) or ".." in study:
        raise HTTPException(status_code=400, detail="Invalid study parameter")
    return study


def _validate_fdr_param(fdr: Optional[str], default: str) -> str:
    if fdr is None or fdr == "":
        return default
    if fdr not in ("bh", "by"):
        raise HTTPException(status_code=400, detail="fdr must be 'bh' or 'by'")
    return fdr


def _require_project(db: Database, project: str) -> int:
    _validate_project_name(project)
    proj_id = db.get_project_id(project)
    if not proj_id:
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return proj_id


def _validate_sha_prefix(prefix: str, label: str = "SHA prefix") -> None:
    if len(prefix) < MIN_SHA_PREFIX or len(prefix) > MAX_SHA_PREFIX:
        raise HTTPException(
            status_code=400,
            detail=f"{label} must be between {MIN_SHA_PREFIX} and {MAX_SHA_PREFIX} characters",
        )


def _brief_commit(commit: Any) -> Dict[str, Any]:
    return {
        "short_sha": commit["short_sha"],
        "subject": commit["subject"],
        "date": (commit["author_date"] or "")[:10],
    }


@lru_cache(maxsize=128)
def _median_ci_indices(n: int) -> Tuple[int, int]:
    """Order-statistic index bounds ``(lo, hi)`` for an exact >=95% CI of the median."""
    if n <= 1:
        return (0, 0)
    k = -1
    for i in range(n // 2):
        if stats.binom.cdf(i, n, 0.5) <= 0.025:
            k = i
        else:
            break
    if k < 0:
        return (0, n - 1)
    return (k, n - 1 - k)


def _resolve_db_path(db_path: Optional[str]) -> str:
    return str(Path(db_path or os.environ.get("REGRESSOR_DB", ROOT_DIR / "regressor.db")).resolve())


def _format_project_entry(p: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "id": p["id"],
        "name": p["name"],
        "repo_url": p["repo_url"],
        "adapter": p["adapter"],
        "total_commits": p["commits"],
        "total_comparisons": p["comparisons"],
        "total_flags": p["flags"],
        "confirmed_regressions": p["confirmed"],
    }


def _sqlite_study_entry(project_names: List[str]) -> Dict[str, Any]:
    return {
        "id": "db",
        "label": "Active Database (SQLite)",
        "source": "sqlite",
        "default_fdr": "bh",
        "projects": project_names,
    }


def _discover_studies(data_dir: Path) -> List[Dict[str, Any]]:
    """List bundled/exported `.json.gz` study datasets in ``data_dir``."""
    studies: List[Dict[str, Any]] = []
    if not data_dir.is_dir():
        return studies
    known_order = {"study1": 0, "study2": 1, "study3": 2}
    for path in sorted(data_dir.glob("*.json.gz"), key=lambda p: p.name):
        if not path.is_file():
            continue
        if path.name in _KNOWN_STUDY_META:
            sid, label, default_fdr = _KNOWN_STUDY_META[path.name]
        else:
            stem = path.name[:-8]  # strip .json.gz
            sid = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._-") or "study"
            label = stem.replace("_", " ")
            default_fdr = "by"
        studies.append({
            "id": sid,
            "label": label,
            "filename": path.name,
            "path": str(path),
            "default_fdr": default_fdr,
            "sort_rank": known_order.get(sid, 100),
        })
    studies.sort(key=lambda s: (s["sort_rank"], s["id"]))
    for s in studies:
        s.pop("sort_rank", None)
    return studies


def _load_archive_dataset(
    study_meta: Dict[str, Any],
    fdr_method: str,
    projects_dir: Path,
) -> Dict[str, Any]:
    """Load a `.json.gz` study archive and compute adjacent batch comparisons."""
    path = Path(study_meta["path"])
    with gzip.open(path, "rt", encoding="utf-8") as f:
        blob = json.load(f)

    project = str(blob.get("project") or "regex")
    raw_commits = blob.get("commits") or []
    commits: List[Dict[str, Any]] = []
    runs_by: Dict[Tuple[int, str], List[float]] = {}
    bench_order: List[str] = []
    bench_seen: set = set()

    for idx, c in enumerate(raw_commits, start=1):
        c_dict = {
            "id": idx,
            "sha": c["sha"],
            "short_sha": c["short_sha"],
            "author_date": c.get("author_date", ""),
            "subject": c.get("subject", ""),
            "build_ok": bool(c.get("build_ok", True)),
            "build_seconds": float(c.get("build_seconds", 0.0)),
            "cpu_model": c.get("cpu_model", "unknown"),
            "rustc_version": c.get("rustc_version", "unknown"),
            "run_started_utc": c.get("run_started_utc", ""),
            "run_finished_utc": c.get("run_finished_utc", ""),
        }
        commits.append(c_dict)
        for bench, medians in (c.get("runs") or {}).items():
            if bench not in bench_seen:
                bench_seen.add(bench)
                bench_order.append(bench)
            runs_by[(idx, bench)] = [float(m) for m in medians]

    benchmarks = sorted(bench_order)
    nf_mult = load_project_noise_floor_multiplier(project, projects_dir=projects_dir)
    comparisons: List[Dict[str, Any]] = []
    comp_id = 0
    for i in range(1, len(commits)):
        base_c = commits[i - 1]
        cand_c = commits[i]
        gap_min = session_gap_minutes(base_c, cand_c)
        for bench in benchmarks:
            b_runs = runs_by.get((base_c["id"], bench), [])
            c_runs = runs_by.get((cand_c["id"], bench), [])
            if len(b_runs) < 5 or len(c_runs) < 5:
                continue
            comp_id += 1
            res = compare_distributions(
                np.asarray(b_runs, dtype=np.float64),
                np.asarray(c_runs, dtype=np.float64),
                alpha=0.01,
                noise_floor_multiplier=nf_mult,
            )
            res.update({
                "id": comp_id,
                "base_commit_id": base_c["id"],
                "cand_commit_id": cand_c["id"],
                "base_sha": base_c["short_sha"],
                "base_full_sha": base_c["sha"],
                "cand_sha": cand_c["short_sha"],
                "cand_full_sha": cand_c["sha"],
                "cand_subject": cand_c["subject"],
                "benchmark": bench,
                "canary_status": "NOT_RECORDED",
                "session_gap_min": gap_min,
            })
            comparisons.append(res)

    bh_fdr_correct(comparisons, alpha=0.05, method=fdr_method)
    return {
        "project": project,
        "commits": commits,
        "benchmarks": benchmarks,
        "runs_by": runs_by,
        "comparisons": comparisons,
    }


def _build_benchmark_series(
    commits: List[Any],
    benchmarks: List[str],
    runs_by: Dict[Any, List[float]],
    flagged: Any,
    triage_entries: Optional[List[Dict[str, Any]]] = None,
    all_flamegraphs: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Build per-benchmark commit time series with dispersion/CI bands, triage status, and session gaps."""
    triage_list = triage_entries or []
    fg_list = all_flamegraphs or []
    flagged_map = flagged if isinstance(flagged, dict) else {k: {} for k in flagged}

    series_by_bench: Dict[str, List[Dict[str, Any]]] = {b: [] for b in benchmarks}
    for commit, gap_min in zip(commits, commit_session_gaps(commits)):
        cid = commit["id"]
        full_sha = commit["sha"]
        short_sha = commit["short_sha"]
        session_break = is_session_break(gap_min)
        date_str = (commit["author_date"] or "")[:10]
        subject = commit["subject"] or ""

        for bench in benchmarks:
            runs = runs_by.get((cid, bench))
            if not runs:
                continue
            arr = np.asarray(runs, dtype=np.float64)
            sorted_arr = np.sort(arr)
            lo_idx, hi_idx = _median_ci_indices(len(sorted_arr))
            p10, med, p90 = np.percentile(arr, [10, 50, 90])
            cv_pct = round(sample_cv(arr) * 100.0, 2)

            flag_row = flagged_map.get((bench, cid))
            is_flagged = flag_row is not None
            triage = match_triage_entry(triage_list, bench, full_sha, short_sha) if triage_list else None
            if triage is not None:
                triage_status: Optional[str] = triage["status"]
                triage_note = triage["note"]
                issue_url = triage["issue_url"]
            elif is_flagged:
                triage_status = flag_row.get("resolution_status") or "unreviewed"
                triage_note = flag_row.get("resolution_note") or ""
                issue_url = None
            else:
                triage_status = None
                triage_note = ""
                issue_url = None

            pt_fgs = match_commit_flamegraphs(full_sha, short_sha, triage, fg_list) if fg_list else []
            series_by_bench[bench].append({
                "sha": short_sha,
                "full_sha": full_sha,
                "commit_id": cid,
                "date": date_str,
                "subject": subject,
                "median_ns": round(float(med), 2),
                "p10_ns": round(float(p10), 2),
                "p90_ns": round(float(p90), 2),
                "ci95_low_ns": round(float(sorted_arr[lo_idx]), 2),
                "ci95_high_ns": round(float(sorted_arr[hi_idx]), 2),
                "cv_pct": cv_pct,
                "flagged": is_flagged,
                "triage_status": triage_status,
                "triage_note": triage_note,
                "issue_url": issue_url,
                "flamegraphs": pt_fgs,
                "session_gap_min": gap_min,
                "session_break": session_break,
            })
    return series_by_bench


def _summarize_benchmark_stats(series_by_bench: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    """Compute compact per-benchmark status counts and duration stats for grid cards."""
    out: Dict[str, Dict[str, Any]] = {}
    for bench, pts in series_by_bench.items():
        flagged_pts = [p for p in pts if p["flagged"]]
        confirmed = sum(1 for p in flagged_pts if p["triage_status"] == "confirmed")
        fps = sum(1 for p in flagged_pts if p["triage_status"] == "false_positive")
        layout = sum(1 for p in pts if p["triage_status"] == "layout_artifact")
        unreviewed = sum(
            1
            for p in flagged_pts
            if p["triage_status"] not in ("confirmed", "false_positive", "layout_artifact")
        )
        medians = [p["median_ns"] for p in pts]
        issues = list(dict.fromkeys(p["issue_url"] for p in pts if p.get("issue_url")))
        fg_map: Dict[str, Dict[str, str]] = {}
        for p in pts:
            for fg in p.get("flamegraphs") or []:
                fg_map[fg["filename"]] = fg
        out[bench] = {
            "point_count": len(pts),
            "flagged_count": len(flagged_pts),
            "confirmed_count": confirmed,
            "false_positive_count": fps,
            "layout_artifact_count": layout,
            "unreviewed_count": unreviewed,
            "latest_median_ns": pts[-1]["median_ns"] if pts else None,
            "latest_cv_pct": pts[-1]["cv_pct"] if pts else None,
            "min_median_ns": min(medians) if medians else None,
            "max_median_ns": max(medians) if medians else None,
            "issue_urls": issues,
            "flamegraphs": list(fg_map.values()),
        }
    return out


def _format_comparison(
    comp: Any,
    triage_entries: Optional[List[Dict[str, Any]]] = None,
    all_flamegraphs: Optional[List[Dict[str, Any]]] = None,
    commits_by_id: Optional[Dict[int, Any]] = None,
) -> Dict[str, Any]:
    """Format a stored or archive comparison row for API responses, overlaying triage metadata."""
    keys = comp.keys() if hasattr(comp, "keys") else ()
    cand_id = comp["cand_commit_id"] if "cand_commit_id" in keys else None
    cand_full = comp["cand_full_sha"] if "cand_full_sha" in keys else ""
    if not cand_full and commits_by_id and cand_id in commits_by_id:
        cand_full = commits_by_id[cand_id]["sha"]
    cand_short = comp["cand_sha"]
    bench = comp["benchmark"]

    triage = match_triage_entry(triage_entries, bench, cand_full, cand_short) if triage_entries else None
    status = triage["status"] if triage else comp["resolution_status"]
    note = triage["note"] if triage else (comp["resolution_note"] or "")
    issue_url = sanitize_issue_url(triage.get("issue_url")) if triage else None
    fgs = match_commit_flamegraphs(cand_full, cand_short, triage, all_flamegraphs) if all_flamegraphs else []

    return {
        "id": comp["id"],
        "base_sha": comp["base_sha"],
        "cand_sha": cand_short,
        "cand_full_sha": cand_full,
        "cand_subject": comp["cand_subject"],
        "benchmark": bench,
        "shift_pct": round(comp["shift_pct"], 2),
        "p_value": comp["p_value"],
        "noise_floor_pct": round(comp["noise_floor_pct"], 2),
        "verdict": comp["verdict"],
        "fdr_significant": bool(comp["fdr_significant"]),
        "resolution_status": status,
        "resolution_note": note,
        "issue_url": issue_url,
        "flamegraphs": fgs,
        "canary_status": comp["canary_status"] or "NOT_RECORDED",
        "session_gap_min": comp["session_gap_min"],
        "session_break": is_session_break(comp["session_gap_min"]),
    }


def _build_distribution_payload(
    commit: Any,
    prev_commit: Any,
    runs_by_benchmark: Dict[str, List[float]],
) -> Dict[str, Any]:
    """Assemble commit metadata, session context, and per-benchmark histograms."""
    bench_data = {
        bench: summarize_distribution(medians, bins=HISTOGRAM_BINS)
        for bench, medians in runs_by_benchmark.items()
    }
    gap_min = session_gap_minutes(prev_commit, commit) if prev_commit is not None else None
    return {
        "commit": {
            "id": commit["id"],
            "sha": commit["sha"],
            "short_sha": commit["short_sha"],
            "subject": commit["subject"],
            "author_date": commit["author_date"],
            "cpu_model": commit["cpu_model"],
            "rustc_version": commit["rustc_version"],
            "build_ok": bool(commit["build_ok"]),
            "build_seconds": commit["build_seconds"],
            "run_started_utc": commit["run_started_utc"] or None,
            "run_finished_utc": commit["run_finished_utc"] or None,
        },
        "session": {
            "prev_short_sha": prev_commit["short_sha"] if prev_commit is not None else None,
            "gap_min": gap_min,
            "session_break": is_session_break(gap_min),
            "threshold_min": SESSION_BREAK_MIN,
        },
        "benchmarks": bench_data,
    }


def _assemble_series_payload(
    name: str,
    commits: List[Any],
    benchmarks: List[str],
    runs_by: Dict[Any, List[float]],
    comparisons: List[Any],
    triage_entries: List[Dict[str, Any]],
    all_flamegraphs: List[Dict[str, Any]],
    study: str,
) -> Dict[str, Any]:
    """Build the `/series` response payload from commits, runs, comparisons, and triage metadata."""
    flagged_map = {
        (c["benchmark"], c["cand_commit_id"]): dict(c)
        for c in comparisons
        if c["verdict"] == "flag" and c["fdr_significant"]
    }
    series_by_bench = _build_benchmark_series(
        commits,
        benchmarks,
        runs_by,
        flagged_map,
        triage_entries=triage_entries,
        all_flamegraphs=all_flamegraphs,
    )
    return {
        "project": name,
        "study": study,
        "benchmarks": benchmarks,
        "total_commits": len(commits),
        "session_break_min": SESSION_BREAK_MIN,
        "series": series_by_bench,
        "benchmark_stats": _summarize_benchmark_stats(series_by_bench),
    }


def _assemble_comparisons_payload(
    commits: List[Any],
    comparisons: List[Any],
    triage_entries: List[Dict[str, Any]],
    all_flamegraphs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build the `/comparisons` response list with triage and flamegraph overlays."""
    commits_by_id = {c["id"]: c for c in commits}
    return [
        _format_comparison(
            c,
            triage_entries=triage_entries,
            all_flamegraphs=all_flamegraphs,
            commits_by_id=commits_by_id,
        )
        for c in comparisons
    ]


def create_app(
    db_path: Optional[str] = None,
    *,
    data_dir: Optional[Path] = None,
    projects_dir: Optional[Path] = None,
    assets_dir: Optional[Path] = None,
) -> FastAPI:
    """Create a FastAPI application bound to a single SQLite database file."""
    resolved_db = _resolve_db_path(db_path)
    resolved_data_dir = (data_dir or (ROOT_DIR / "data")).resolve()
    resolved_projects_dir = (projects_dir or (ROOT_DIR / "projects")).resolve()
    resolved_assets_dir = (assets_dir or (ROOT_DIR / "assets" / "flamegraphs")).resolve()

    db = Database(resolved_db)
    study_cache: Dict[Tuple[str, str, int], Dict[str, Any]] = {}

    def _get_study_dataset(study_id: str, fdr: Optional[str]) -> Dict[str, Any]:
        studies = {s["id"]: s for s in _discover_studies(resolved_data_dir)}
        meta = studies.get(study_id)
        if meta is None:
            raise HTTPException(status_code=404, detail=f"Study '{study_id}' not found")
        fdr_method = _validate_fdr_param(fdr, meta["default_fdr"])
        mtime_ns = Path(meta["path"]).stat().st_mtime_ns
        key = (study_id, fdr_method, mtime_ns)
        if key not in study_cache:
            study_cache[key] = _load_archive_dataset(meta, fdr_method, resolved_projects_dir)
        return study_cache[key]

    def _load_project_dataset(
        name: str,
        study: Optional[str],
        fdr: Optional[str],
        *,
        include_runs: bool = False,
    ) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
        _validate_project_name(name)
        study_id = _validate_study_param(study)
        triage_entries = load_triage_entries(
            name, projects_dir=resolved_projects_dir, assets_dir=resolved_assets_dir
        )
        all_flamegraphs = discover_flamegraphs(assets_dir=resolved_assets_dir)

        if study_id is not None:
            ds = _get_study_dataset(study_id, fdr)
            if ds["project"] != name:
                raise HTTPException(status_code=404, detail=f"Project '{name}' not found in study '{study_id}'")
            return study_id, ds, triage_entries, all_flamegraphs

        proj_id = _require_project(db, name)
        ds = {
            "commits": db.get_project_commits(proj_id),
            "comparisons": db.get_project_comparisons(proj_id),
            "benchmarks": db.get_project_benchmarks(proj_id),
            "runs_by": db.get_project_runs(proj_id) if include_runs else {},
        }
        return "db", ds, triage_entries, all_flamegraphs

    app = FastAPI(
        title="regressor: Performance Ledger API",
        description="Read-only performance ledger, sampling distribution drill-down, and ad-hoc commit comparison API.",
        version="2.2.0",
        openapi_tags=OPENAPI_TAGS,
    )

    # The UI is served from this same origin, so CORS is only a convenience for a dev server on
    # another local port. No credentials, no wildcard.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def add_security_headers(request, call_next):
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response

    ui_dir = ROOT_DIR / "ui"
    if resolved_assets_dir.is_dir():
        app.mount("/flamegraphs", StaticFiles(directory=str(resolved_assets_dir)), name="flamegraphs")
    if ui_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(ui_dir)), name="static")

    @app.get("/", response_class=HTMLResponse, tags=["ui"], summary="Serve the dashboard UI")
    def index_page():
        """Serve the embedded single-page dashboard (`ui/index.html`) or a minimal fallback."""
        index_file = ui_dir / "index.html"
        if index_file.exists():
            return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
        return HTMLResponse(content="<h1>regressor API</h1><p>UI not found.</p>")

    @app.get("/api/studies", tags=["projects"], summary="List available study datasets")
    def list_studies():
        """Return the active SQLite DB plus any bundled `.json.gz` study datasets in `data/`."""
        db_projects = [p["name"] for p in db.get_all_projects_summary()]
        items: List[Dict[str, Any]] = [_sqlite_study_entry(db_projects)]
        for s in _discover_studies(resolved_data_dir):
            proj_name = "regex"
            try:
                with gzip.open(s["path"], "rt", encoding="utf-8") as fh:
                    blob = json.load(fh)
                if isinstance(blob, dict) and isinstance(blob.get("project"), str):
                    proj_name = blob["project"]
            except (OSError, json.JSONDecodeError):
                pass
            items.append({
                "id": s["id"],
                "label": s["label"],
                "source": "archive",
                "filename": s["filename"],
                "default_fdr": s["default_fdr"],
                "projects": [proj_name],
            })
        return items

    @app.get("/api/flamegraphs", tags=["projects"], summary="List available SVG flamegraphs")
    def list_flamegraphs():
        """Return all differential/profile SVGs discovered in `assets/flamegraphs/`."""
        return discover_flamegraphs(assets_dir=resolved_assets_dir)

    @app.get("/api/projects", tags=["projects"], summary="List registered projects")
    def list_projects():
        """Return every registered project along with its commit, comparison, and flag counts."""
        return [_format_project_entry(p) for p in db.get_all_projects_summary()]

    @app.get(
        "/api/projects/{name}/series",
        tags=["projects"],
        summary="Get benchmark time series",
        responses={400: {"description": "Invalid project name"}, 404: {"description": "Project not found"}},
    )
    def get_project_series(
        name: str,
        study: Annotated[Optional[str], Query(description="Dataset ID ('db' or study archive ID).")] = None,
        fdr: Annotated[Optional[str], Query(description="FDR method ('bh' or 'by') for archive studies.")] = None,
    ):
        """Return per-benchmark median, dispersion/CI bands, triage status, flamegraphs, and session breaks."""
        study_label, ds, triage_entries, all_flamegraphs = _load_project_dataset(
            name, study, fdr, include_runs=True
        )
        return _assemble_series_payload(
            name,
            ds["commits"],
            ds["benchmarks"],
            ds["runs_by"],
            ds["comparisons"],
            triage_entries,
            all_flamegraphs,
            study_label,
        )

    @app.get(
        "/api/projects/{name}/comparisons",
        tags=["projects"],
        summary="List stored pairwise comparisons",
        responses={400: {"description": "Invalid project name"}, 404: {"description": "Project not found"}},
    )
    def get_project_comparisons(
        name: str,
        study: Annotated[Optional[str], Query(description="Dataset ID ('db' or study archive ID).")] = None,
        fdr: Annotated[Optional[str], Query(description="FDR method ('bh' or 'by') for archive studies.")] = None,
    ):
        """Return all comparison rows with overlaid triage metadata, issue links, and flamegraphs."""
        _, ds, triage_entries, all_flamegraphs = _load_project_dataset(name, study, fdr)
        return _assemble_comparisons_payload(
            ds["commits"], ds["comparisons"], triage_entries, all_flamegraphs
        )

    @app.get(
        "/api/projects/{name}/summary",
        tags=["projects"],
        summary="Get publishable project summary",
        responses={400: {"description": "Invalid project name"}, 404: {"description": "Project not found"}},
    )
    def get_project_summary(
        name: str,
        study: Annotated[Optional[str], Query(description="Dataset ID ('db' or study archive ID).")] = None,
        fdr: Annotated[Optional[str], Query(description="FDR method ('bh' or 'by') for archive studies.")] = None,
    ):
        """Compute publishable metrics (commits, comparisons, flags, FP rate + Wilson CI, layout artifacts, issues)."""
        study_label, ds, triage_entries, all_flamegraphs = _load_project_dataset(name, study, fdr)
        return compute_summary_from_records(
            project=name,
            commits=ds["commits"],
            comparisons=ds["comparisons"],
            triage_entries=triage_entries,
            benchmarks=ds["benchmarks"],
            flamegraphs=all_flamegraphs,
            study=study_label,
        )

    @app.get(
        "/api/commits/{sha}/distribution",
        tags=["commits"],
        summary="Inspect commit run distribution",
        responses={
            400: {"description": "Invalid SHA prefix or project parameter"},
            404: {"description": "Project or commit not found"},
        },
    )
    def get_commit_distribution(
        sha: str,
        project: Annotated[Optional[str], Query(description="Optional project name to disambiguate SHA lookup.")] = None,
        study: Annotated[Optional[str], Query(description="Dataset ID ('db' or study archive ID).")] = None,
    ):
        """Return commit metadata, session-gap context, and per-benchmark summary stats/histograms."""
        _validate_sha_prefix(sha)
        study_id = _validate_study_param(study)
        if study_id is not None:
            if project is not None:
                _validate_project_name(project)
            ds = _get_study_dataset(study_id, None)
            if project is not None and ds["project"] != project:
                raise HTTPException(status_code=404, detail=f"Project '{project}' not found in study '{study_id}'")
            commit, err = resolve_commit_prefix(ds["commits"], sha)
            if err or commit is None:
                raise HTTPException(status_code=404, detail=f"Commit '{sha}' not found")
            idx = ds["commits"].index(commit)
            prev_commit = ds["commits"][idx - 1] if idx > 0 else None
            runs_by_benchmark = {
                bench: ds["runs_by"][(commit["id"], bench)]
                for bench in ds["benchmarks"]
                if (commit["id"], bench) in ds["runs_by"]
            }
            return _build_distribution_payload(commit, prev_commit, runs_by_benchmark)

        proj_id = _require_project(db, project) if project is not None else None
        details = db.get_commit_details(sha, project_id=proj_id)
        if details is None:
            raise HTTPException(status_code=404, detail=f"Commit '{sha}' not found")
        return _build_distribution_payload(details["commit"], details["prev_commit"], details["runs_by_benchmark"])

    @app.post(
        "/api/compare",
        tags=["compare"],
        summary="Compare two commits ad hoc",
        responses={
            400: {"description": "Invalid parameters, ambiguous/missing commit, or identical commits"},
            404: {"description": "Project not found"},
        },
    )
    def compare_commits(req: CompareRequest):
        """Run Mann-Whitney U and Hodges-Lehmann shift comparison between two arbitrary commits."""
        _validate_project_name(req.project)
        study_id = _validate_study_param(req.study)
        for label, prefix in (("base_sha", req.base_sha), ("cand_sha", req.cand_sha)):
            _validate_sha_prefix(prefix, label=label)

        if study_id is not None:
            ds = _get_study_dataset(study_id, None)
            if ds["project"] != req.project:
                raise HTTPException(status_code=404, detail=f"Project '{req.project}' not found in study '{study_id}'")
            commits = ds["commits"]
            base_c, cand_c, err = resolve_commit_pair(commits, req.base_sha, req.cand_sha)
            if err:
                detail = err if "same commit" in err else f"Could not resolve commit: {err}"
                raise HTTPException(status_code=400, detail=detail)
            base_runs = {
                b: ds["runs_by"][(base_c["id"], b)]
                for b in ds["benchmarks"]
                if (base_c["id"], b) in ds["runs_by"]
            }
            cand_runs = {
                b: ds["runs_by"][(cand_c["id"], b)]
                for b in ds["benchmarks"]
                if (cand_c["id"], b) in ds["runs_by"]
            }
        else:
            proj_id = _require_project(db, req.project)
            commits = db.get_project_commits(proj_id)
            base_c, cand_c, err = resolve_commit_pair(commits, req.base_sha, req.cand_sha)
            if err:
                detail = err if "same commit" in err else f"Could not resolve commit: {err}"
                raise HTTPException(status_code=400, detail=detail)
            base_runs = db.get_commit_runs_by_benchmark(base_c["id"])
            cand_runs = db.get_commit_runs_by_benchmark(cand_c["id"])

        results = compare_benchmark_runs(base_runs, cand_runs, min_runs=MIN_COMPARE_RUNS)
        return {
            "project": req.project,
            "base_commit": _brief_commit(base_c),
            "cand_commit": _brief_commit(cand_c),
            "comparisons": results,
        }

    return app


def export_static_site(
    out_dir: Path,
    db_path: Optional[str] = None,
    *,
    data_dir: Optional[Path] = None,
    projects_dir: Optional[Path] = None,
    assets_dir: Optional[Path] = None,
    ui_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Export a self-contained static dashboard bundle for GitHub Pages / static hosting."""
    import shutil

    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / ".nojekyll").write_text("", encoding="utf-8")

    resolved_db = _resolve_db_path(db_path)
    resolved_data = (data_dir or (ROOT_DIR / "data")).resolve()
    resolved_projects = (projects_dir or (ROOT_DIR / "projects")).resolve()
    resolved_assets = (assets_dir or (ROOT_DIR / "assets" / "flamegraphs")).resolve()
    resolved_ui = (ui_dir or (ROOT_DIR / "ui")).resolve()

    # Copy UI assets & flamegraphs
    ui_html_path = resolved_ui / "index.html"
    if not ui_html_path.is_file():
        raise FileNotFoundError(f"UI template not found: {ui_html_path}")
    html_text = ui_html_path.read_text(encoding="utf-8")
    html_text = (
        html_text
        .replace('src="/static/', 'src="static/')
        .replace('src="/flamegraphs/', 'src="flamegraphs/')
        .replace('href="/flamegraphs/', 'href="flamegraphs/')
    )
    html_text = html_text.replace("</head>", "<script>window.__REGRESSOR_STATIC__ = true;</script>\n</head>", 1)
    (out / "index.html").write_text(html_text, encoding="utf-8")

    vendor_src = resolved_ui / "vendor" / "chart.umd.js"
    if vendor_src.is_file():
        vendor_dst = out / "static" / "vendor" / "chart.umd.js"
        vendor_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(vendor_src, vendor_dst)

    all_flamegraphs = discover_flamegraphs(assets_dir=resolved_assets)
    fg_out_dir = out / "flamegraphs"
    fg_out_dir.mkdir(parents=True, exist_ok=True)
    for fg in all_flamegraphs:
        shutil.copy2(resolved_assets / fg["filename"], fg_out_dir / fg["filename"])

    api_dir = out / "api"
    api_dir.mkdir(parents=True, exist_ok=True)

    def _write_json(rel_path: str, payload: Any) -> None:
        target = (api_dir / rel_path).resolve()
        if api_dir not in target.parents:
            raise ValueError(f"Unsafe export path: {rel_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")

    _write_json("flamegraphs.json", all_flamegraphs)

    db = Database(resolved_db)
    projects = [_format_project_entry(p) for p in db.get_all_projects_summary()]
    _write_json("projects.json", projects)

    exported_studies: List[Dict[str, Any]] = []
    files_written = 0

    def _export_dataset(
        study_id: str,
        proj_name: str,
        commits: List[Any],
        benchmarks: List[str],
        runs_by: Dict[Any, List[float]],
        comparisons: List[Any],
    ) -> None:
        nonlocal files_written
        triage_entries = load_triage_entries(
            proj_name, projects_dir=resolved_projects, assets_dir=resolved_assets
        )
        prefix = f"data/{study_id}/{proj_name}"
        _write_json(
            f"{prefix}/series.json",
            _assemble_series_payload(
                proj_name, commits, benchmarks, runs_by, comparisons, triage_entries, all_flamegraphs, study_id
            ),
        )
        _write_json(
            f"{prefix}/comparisons.json",
            _assemble_comparisons_payload(commits, comparisons, triage_entries, all_flamegraphs),
        )
        _write_json(
            f"{prefix}/summary.json",
            compute_summary_from_records(
                project=proj_name,
                commits=commits,
                comparisons=comparisons,
                triage_entries=triage_entries,
                benchmarks=benchmarks,
                flamegraphs=all_flamegraphs,
                study=study_id,
            ),
        )
        files_written += 3
        for idx, commit in enumerate(commits):
            prev_c = commits[idx - 1] if idx > 0 else None
            runs_by_bench = {b: runs_by[(commit["id"], b)] for b in benchmarks if (commit["id"], b) in runs_by}
            dist = _build_distribution_payload(commit, prev_c, runs_by_bench)
            short_sha = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(commit["short_sha"]))
            _write_json(f"{prefix}/distributions/{short_sha}.json", dist)
            files_written += 1

    if projects:
        exported_studies.append(_sqlite_study_entry([p["name"] for p in projects]))
        for p in projects:
            pid = p["id"]
            _export_dataset(
                "db",
                p["name"],
                db.get_project_commits(pid),
                db.get_project_benchmarks(pid),
                db.get_project_runs(pid),
                db.get_project_comparisons(pid),
            )

    for s in _discover_studies(resolved_data):
        ds = _load_archive_dataset(s, s["default_fdr"], resolved_projects)
        exported_studies.append({
            "id": s["id"],
            "label": s["label"],
            "source": "archive",
            "filename": s["filename"],
            "default_fdr": s["default_fdr"],
            "projects": [ds["project"]],
        })
        _export_dataset(
            s["id"],
            ds["project"],
            ds["commits"],
            ds["benchmarks"],
            ds["runs_by"],
            ds["comparisons"],
        )

    _write_json("studies.json", exported_studies)
    return {
        "out_dir": str(out),
        "studies": len(exported_studies),
        "projects": len(projects),
        "flamegraphs": len(all_flamegraphs),
        "files_written": files_written + 4,
    }


_default_app: Optional[FastAPI] = None


def __getattr__(name: str):
    """Lazily build `server.app:app` for `uvicorn server.app:app` without import-time DB side effects."""
    global _default_app
    if name == "app":
        if _default_app is None:
            _default_app = create_app()
        return _default_app
    raise AttributeError(name)
