"""
server/app.py
FastAPI backend for the regressor dashboard: time-series, comparisons, distribution drill-down
and ad-hoc comparisons from SQLite.

`create_app(db_path)` returns an independent application bound to one database file, so tests
and multiple servers never share state. For `uvicorn server.app:app` the module-level `app` uses
the REGRESSOR_DB environment variable (default: ./regressor.db next to the repo root).
"""

import os
from pathlib import Path
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from core.db import Database, resolve_commit_prefix
from core.detector import compare_distributions
from core.session import SESSION_BREAK_MIN, is_session_break, session_gap_minutes

ROOT_DIR = Path(__file__).parent.parent.resolve()
MIN_SHA_PREFIX = 4
MAX_SHA_PREFIX = 64
MAX_PROJECT_LEN = 64
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


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = "regex"
    base_sha: str
    cand_sha: str


def create_app(db_path: Optional[str] = None) -> FastAPI:
    db = Database(str(Path(db_path or os.environ.get("REGRESSOR_DB", ROOT_DIR / "regressor.db")).resolve()))
    app = FastAPI(title="regressor: Performance Ledger API", version="2.1.0")

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
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        response.headers.setdefault("Content-Security-Policy", CSP_POLICY)
        return response

    flamegraphs_dir = ROOT_DIR / "assets" / "flamegraphs"
    ui_dir = ROOT_DIR / "ui"
    if flamegraphs_dir.is_dir():
        app.mount("/flamegraphs", StaticFiles(directory=str(flamegraphs_dir)), name="flamegraphs")
    if ui_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(ui_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index_page():
        index_file = ui_dir / "index.html"
        if index_file.exists():
            return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
        return HTMLResponse(content="<h1>regressor API</h1><p>UI not found.</p>")

    @app.get("/api/projects")
    def list_projects():
        res = []
        for p in db.get_all_projects():
            s = db.project_summary(p["id"])
            res.append({
                "id": p["id"], "name": p["name"], "repo_url": p["repo_url"], "adapter": p["adapter"],
                "total_commits": s["commits"], "total_comparisons": s["comparisons"],
                "total_flags": s["flags"], "confirmed_regressions": s["confirmed"],
            })
        return res

    @app.get("/api/projects/{name}/series")
    def get_project_series(name: str):
        proj_id = db.get_project_id(name)
        if not proj_id:
            raise HTTPException(status_code=404, detail=f"Project '{name}' not found")

        commits = db.get_project_commits(proj_id)
        flagged = {(c["benchmark"], c["cand_commit_id"]) for c in db.get_project_comparisons(proj_id)
                   if c["verdict"] == "flag" and c["fdr_significant"]}
        benchmarks = db.get_project_benchmarks(proj_id)
        runs_by = db.get_project_runs(proj_id)          # one query, not commits x benchmarks

        series_by_bench = {b: [] for b in benchmarks}
        prev_commit = None
        for c in commits:
            cid = c["id"]
            gap_min = session_gap_minutes(prev_commit, c) if prev_commit is not None else None
            prev_commit = c
            for b in benchmarks:
                runs = runs_by.get((cid, b))
                if not runs:
                    continue
                arr = np.asarray(runs, dtype=np.float64)
                p10, med, p90 = np.percentile(arr, [10, 50, 90])
                series_by_bench[b].append({
                    "sha": c["short_sha"], "commit_id": cid, "date": (c["author_date"] or "")[:10],
                    "subject": c["subject"] or "", "median_ns": round(float(med), 2),
                    "p10_ns": round(float(p10), 2), "p90_ns": round(float(p90), 2),
                    "flagged": (b, cid) in flagged, "session_gap_min": gap_min,
                    "session_break": is_session_break(gap_min),
                })

        return {"project": name, "benchmarks": benchmarks, "total_commits": len(commits),
                "session_break_min": SESSION_BREAK_MIN, "series": series_by_bench}

    @app.get("/api/projects/{name}/comparisons")
    def get_project_comparisons(name: str):
        proj_id = db.get_project_id(name)
        if not proj_id:
            raise HTTPException(status_code=404, detail=f"Project '{name}' not found")
        return [{
            "id": c["id"], "base_sha": c["base_sha"], "cand_sha": c["cand_sha"],
            "cand_subject": c["cand_subject"], "benchmark": c["benchmark"],
            "shift_pct": round(c["shift_pct"], 2), "p_value": c["p_value"],
            "noise_floor_pct": round(c["noise_floor_pct"], 2), "verdict": c["verdict"],
            "fdr_significant": bool(c["fdr_significant"]), "resolution_status": c["resolution_status"],
            "resolution_note": c["resolution_note"] or "",
            "canary_status": c["canary_status"] or "NOT_RECORDED",
            "session_gap_min": c["session_gap_min"],
            "session_break": is_session_break(c["session_gap_min"]),
        } for c in db.get_project_comparisons(proj_id)]

    @app.get("/api/commits/{sha}/distribution")
    def get_commit_distribution(sha: str, project: Optional[str] = Query(None)):
        if len(sha) < MIN_SHA_PREFIX or len(sha) > MAX_SHA_PREFIX:
            raise HTTPException(
                status_code=400,
                detail=f"SHA prefix must be between {MIN_SHA_PREFIX} and {MAX_SHA_PREFIX} characters",
            )
        if project is not None and (not project or len(project) > MAX_PROJECT_LEN):
            raise HTTPException(status_code=400, detail="Invalid project parameter")
        n = len(sha)
        # substr() comparison instead of LIKE: '%' and '_' in user input are not wildcards.
        with db.get_conn() as conn:
            sql = ("SELECT * FROM commits WHERE (substr(sha, 1, ?) = ? OR substr(short_sha, 1, ?) = ?)")
            args = [n, sha, n, sha]
            if project:
                pid = db.get_project_id(project)
                if not pid:
                    raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
                sql += " AND project_id = ?"
                args.append(pid)
            commit = conn.execute(sql + " ORDER BY id DESC LIMIT 1", args).fetchone()
            if not commit:
                raise HTTPException(status_code=404, detail=f"Commit '{sha}' not found")
            cid = commit["id"]
            run_rows = conn.execute("SELECT * FROM runs WHERE commit_id = ? ORDER BY benchmark ASC, rep_index ASC",
                                    (cid,)).fetchall()
            prev_commit = conn.execute(
                "SELECT * FROM commits WHERE project_id = ? AND id < ? ORDER BY id DESC LIMIT 1",
                (commit["project_id"], cid)).fetchone()

        bench_data = {}
        for b in sorted({r["benchmark"] for r in run_rows}):
            medians = [r["median_ns"] for r in run_rows if r["benchmark"] == b]
            arr = np.asarray(medians, dtype=np.float64)
            mean = float(np.mean(arr))
            std = float(np.std(arr, ddof=1)) if len(arr) > 1 else float(np.std(arr))
            hist, edges = np.histogram(arr, bins=10)
            bench_data[b] = {
                "rep_count": len(medians), "rep_medians": [round(x, 1) for x in medians],
                "median_ns": round(float(np.median(arr)), 1), "mean_ns": round(mean, 1),
                "std_ns": round(std, 1), "cv_pct": round(std / mean * 100.0 if mean > 0 else 0.0, 2),
                "min_ns": round(float(arr.min()), 1), "max_ns": round(float(arr.max()), 1),
                "histogram": [{"bin_start_ns": round(float(edges[i]), 1), "bin_end_ns": round(float(edges[i + 1]), 1),
                               "count": int(hist[i])} for i in range(len(hist))],
            }

        gap_min = session_gap_minutes(prev_commit, commit) if prev_commit is not None else None
        return {
            "commit": {
                "id": commit["id"], "sha": commit["sha"], "short_sha": commit["short_sha"],
                "subject": commit["subject"], "author_date": commit["author_date"],
                "cpu_model": commit["cpu_model"], "rustc_version": commit["rustc_version"],
                "build_ok": bool(commit["build_ok"]), "build_seconds": commit["build_seconds"],
                "run_started_utc": commit["run_started_utc"] or None,
                "run_finished_utc": commit["run_finished_utc"] or None,
            },
            "session": {
                "prev_short_sha": prev_commit["short_sha"] if prev_commit is not None else None,
                "gap_min": gap_min, "session_break": is_session_break(gap_min),
                "threshold_min": SESSION_BREAK_MIN,
            },
            "benchmarks": bench_data,
        }

    @app.post("/api/compare")
    def compare_commits(req: CompareRequest):
        if not req.project or len(req.project) > MAX_PROJECT_LEN:
            raise HTTPException(status_code=400, detail="Invalid project parameter")
        proj_id = db.get_project_id(req.project)
        if not proj_id:
            raise HTTPException(status_code=404, detail=f"Project '{req.project}' not found")
        for label, prefix in (("base_sha", req.base_sha), ("cand_sha", req.cand_sha)):
            if len(prefix) < MIN_SHA_PREFIX or len(prefix) > MAX_SHA_PREFIX:
                raise HTTPException(
                    status_code=400,
                    detail=f"{label} must be between {MIN_SHA_PREFIX} and {MAX_SHA_PREFIX} characters",
                )
        commits = db.get_project_commits(proj_id)
        base_c, err_b = resolve_commit_prefix(commits, req.base_sha)
        cand_c, err_c = resolve_commit_prefix(commits, req.cand_sha)
        if err_b or err_c:
            raise HTTPException(status_code=400, detail=f"Could not resolve commit: {err_b or err_c}")
        if base_c["id"] == cand_c["id"]:
            raise HTTPException(status_code=400, detail="base_sha and cand_sha resolve to the same commit.")

        runs_by = db.get_project_runs(proj_id)
        benches = sorted({b for (cid, b) in runs_by if cid in (base_c["id"], cand_c["id"])})
        results = []
        for b in benches:
            b_runs, c_runs = runs_by.get((base_c["id"], b), []), runs_by.get((cand_c["id"], b), [])
            if len(b_runs) < 3 or len(c_runs) < 3:
                continue
            res = compare_distributions(np.asarray(b_runs, dtype=np.float64), np.asarray(c_runs, dtype=np.float64))
            res["benchmark"] = b
            results.append(res)

        def brief(c):
            return {"short_sha": c["short_sha"], "subject": c["subject"], "date": (c["author_date"] or "")[:10]}
        return {"project": req.project, "base_commit": brief(base_c), "cand_commit": brief(cand_c),
                "comparisons": results}

    return app


_default_app: Optional[FastAPI] = None


def __getattr__(name: str):
    """Lazy `server.app:app` for `uvicorn server.app:app`. Importing this module must not touch
    the filesystem (an eager create_app() would create an empty regressor.db as a side effect)."""
    global _default_app
    if name == "app":
        if _default_app is None:
            _default_app = create_app()
        return _default_app
    raise AttributeError(name)
