"""
server/app.py
FastAPI backend for the regressor dashboard and JSON API.

`create_app(db_path)` returns an independent FastAPI instance bound to one SQLite
database file, keeping tests and multiple server instances isolated. For
`uvicorn server.app:app`, module-level `__getattr__` lazily builds the default
app from `REGRESSOR_DB` (default: `./regressor.db` at the repo root) so importing
this module has no filesystem side effects.
"""

import os
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from core.db import MIN_SHA_PREFIX, Database, resolve_commit_pair
from core.detector import compare_benchmark_runs, summarize_distribution
from core.session import SESSION_BREAK_MIN, commit_session_gaps, is_session_break, session_gap_minutes

ROOT_DIR = Path(__file__).parent.parent.resolve()
MAX_SHA_PREFIX = 64
MAX_PROJECT_LEN = 64
MIN_COMPARE_RUNS = 3
HISTOGRAM_BINS = 10

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


def _validate_project_name(project: Optional[str]) -> None:
    if not project or len(project) > MAX_PROJECT_LEN:
        raise HTTPException(status_code=400, detail="Invalid project parameter")


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


def _build_benchmark_series(
    commits: List[Any],
    benchmarks: List[str],
    runs_by: Dict[Any, List[float]],
    flagged: set,
) -> Dict[str, List[Dict[str, Any]]]:
    """Build per-benchmark commit time series with p10/median/p90 bands and session gaps."""
    series_by_bench: Dict[str, List[Dict[str, Any]]] = {b: [] for b in benchmarks}
    for commit, gap_min in zip(commits, commit_session_gaps(commits)):
        cid = commit["id"]
        session_break = is_session_break(gap_min)
        date_str = (commit["author_date"] or "")[:10]
        subject = commit["subject"] or ""

        for bench in benchmarks:
            runs = runs_by.get((cid, bench))
            if not runs:
                continue
            p10, med, p90 = np.percentile(np.asarray(runs, dtype=np.float64), [10, 50, 90])
            series_by_bench[bench].append({
                "sha": commit["short_sha"],
                "commit_id": cid,
                "date": date_str,
                "subject": subject,
                "median_ns": round(float(med), 2),
                "p10_ns": round(float(p10), 2),
                "p90_ns": round(float(p90), 2),
                "flagged": (bench, cid) in flagged,
                "session_gap_min": gap_min,
                "session_break": session_break,
            })
    return series_by_bench


def _format_comparison(comp: Any) -> Dict[str, Any]:
    """Format a stored comparison row for API responses."""
    return {
        "id": comp["id"],
        "base_sha": comp["base_sha"],
        "cand_sha": comp["cand_sha"],
        "cand_subject": comp["cand_subject"],
        "benchmark": comp["benchmark"],
        "shift_pct": round(comp["shift_pct"], 2),
        "p_value": comp["p_value"],
        "noise_floor_pct": round(comp["noise_floor_pct"], 2),
        "verdict": comp["verdict"],
        "fdr_significant": bool(comp["fdr_significant"]),
        "resolution_status": comp["resolution_status"],
        "resolution_note": comp["resolution_note"] or "",
        "canary_status": comp["canary_status"] or "NOT_RECORDED",
        "session_gap_min": comp["session_gap_min"],
        "session_break": is_session_break(comp["session_gap_min"]),
    }


def create_app(db_path: Optional[str] = None) -> FastAPI:
    """Create a FastAPI application bound to a single SQLite database file."""
    resolved_db = str(Path(db_path or os.environ.get("REGRESSOR_DB", ROOT_DIR / "regressor.db")).resolve())
    db = Database(resolved_db)

    app = FastAPI(
        title="regressor: Performance Ledger API",
        description="Read-only performance ledger, sampling distribution drill-down, and ad-hoc commit comparison API.",
        version="2.1.0",
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

    flamegraphs_dir = ROOT_DIR / "assets" / "flamegraphs"
    ui_dir = ROOT_DIR / "ui"
    if flamegraphs_dir.is_dir():
        app.mount("/flamegraphs", StaticFiles(directory=str(flamegraphs_dir)), name="flamegraphs")
    if ui_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(ui_dir)), name="static")

    @app.get("/", response_class=HTMLResponse, tags=["ui"], summary="Serve the dashboard UI")
    def index_page():
        """Serve the embedded single-page dashboard (`ui/index.html`) or a minimal fallback."""
        index_file = ui_dir / "index.html"
        if index_file.exists():
            return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
        return HTMLResponse(content="<h1>regressor API</h1><p>UI not found.</p>")

    @app.get("/api/projects", tags=["projects"], summary="List registered projects")
    def list_projects():
        """Return every registered project along with its commit, comparison, and flag counts."""
        return [
            {
                "id": p["id"],
                "name": p["name"],
                "repo_url": p["repo_url"],
                "adapter": p["adapter"],
                "total_commits": p["commits"],
                "total_comparisons": p["comparisons"],
                "total_flags": p["flags"],
                "confirmed_regressions": p["confirmed"],
            }
            for p in db.get_all_projects_summary()
        ]

    @app.get(
        "/api/projects/{name}/series",
        tags=["projects"],
        summary="Get benchmark time series",
        responses={400: {"description": "Invalid project name"}, 404: {"description": "Project not found"}},
    )
    def get_project_series(name: str):
        """Return per-benchmark median and p10-p90 bands across commits, plus session-break flags."""
        proj_id = _require_project(db, name)
        commits = db.get_project_commits(proj_id)
        flagged = {
            (c["benchmark"], c["cand_commit_id"])
            for c in db.get_project_comparisons(proj_id)
            if c["verdict"] == "flag" and c["fdr_significant"]
        }
        benchmarks = db.get_project_benchmarks(proj_id)
        runs_by = db.get_project_runs(proj_id)
        series_by_bench = _build_benchmark_series(commits, benchmarks, runs_by, flagged)
        return {
            "project": name,
            "benchmarks": benchmarks,
            "total_commits": len(commits),
            "session_break_min": SESSION_BREAK_MIN,
            "series": series_by_bench,
        }

    @app.get(
        "/api/projects/{name}/comparisons",
        tags=["projects"],
        summary="List stored pairwise comparisons",
        responses={400: {"description": "Invalid project name"}, 404: {"description": "Project not found"}},
    )
    def get_project_comparisons(name: str):
        """Return all stored batch comparison rows and triage metadata for a project."""
        proj_id = _require_project(db, name)
        return [_format_comparison(c) for c in db.get_project_comparisons(proj_id)]

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
    ):
        """Return commit metadata, session-gap context, and per-benchmark summary stats/histograms."""
        _validate_sha_prefix(sha)
        proj_id = _require_project(db, project) if project is not None else None
        details = db.get_commit_details(sha, project_id=proj_id)
        if details is None:
            raise HTTPException(status_code=404, detail=f"Commit '{sha}' not found")

        commit = details["commit"]
        prev_commit = details["prev_commit"]
        bench_data = {
            bench: summarize_distribution(medians, bins=HISTOGRAM_BINS)
            for bench, medians in details["runs_by_benchmark"].items()
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
        proj_id = _require_project(db, req.project)
        for label, prefix in (("base_sha", req.base_sha), ("cand_sha", req.cand_sha)):
            _validate_sha_prefix(prefix, label=label)

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


_default_app: Optional[FastAPI] = None


def __getattr__(name: str):
    """Lazily build `server.app:app` for `uvicorn server.app:app` without import-time DB side effects."""
    global _default_app
    if name == "app":
        if _default_app is None:
            _default_app = create_app()
        return _default_app
    raise AttributeError(name)
