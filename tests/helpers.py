"""
tests/helpers.py
Shared test fixtures/helpers for stubbed adapters, SQLite seeding, and FastAPI test clients.
"""

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pytest

from adapters.base import BaseAdapter
from core.db import Database
from core.models import BuildResult


class StubAdapter(BaseAdapter):
    """Minimal deterministic adapter stub with no-op builds and single-benchmark default."""

    bench_name = "b1"

    def list_benchmarks(self) -> List[str]:
        return [self.bench_name]

    def build(self, commit_ref: str, workdir: Optional[Path] = None) -> BuildResult:
        return BuildResult(ok=True, seconds=0.0, log_tail="", artifact=commit_ref)

    def run(
        self,
        bench_name: str,
        iters: int,
        warmup: int,
        inject_ns: int = 0,
        artifact: Optional[str] = None,
    ) -> List[float]:
        raise NotImplementedError


class ScriptedAdapter(StubAdapter):
    """Adapter returning scripted per-call sample batches for bisect and interleaved tests."""

    def __init__(
        self,
        commits: Sequence[str],
        script: Dict[str, Sequence[float]],
        default_bad_from: int,
        *,
        good_ns: float = 1000.0,
        bad_ns: float = 1080.0,
        reps_per_call: int = 5,
        bench_name: str = "b1",
    ):
        self.commits = list(commits)
        self.script = script
        self.calls: Dict[str, int] = {}
        self.default_bad_from = default_bad_from
        self.good_ns = good_ns
        self.bad_ns = bad_ns
        self.reps_per_call = reps_per_call
        self.bench_name = bench_name

    def run(
        self,
        bench_name: str,
        iters: int,
        warmup: int,
        inject_ns: int = 0,
        artifact: Optional[str] = None,
    ) -> List[float]:
        assert artifact is not None
        if artifact == self.commits[0]:
            return [self.good_ns] * self.reps_per_call
        k = self.calls.get(artifact, 0)
        self.calls[artifact] = k + 1
        if artifact in self.script:
            seq = self.script[artifact]
            return [seq[min(k, len(seq) - 1)]] * self.reps_per_call
        val = self.bad_ns if self.commits.index(artifact) >= self.default_bad_from else self.good_ns
        return [val] * self.reps_per_call


def seed_project_db(
    db_path: Path,
    *,
    project_name: str = "demo",
    repo_url: str = "",
    adapter: str = "PyMicroAdapter",
    commits: Optional[Sequence[Dict[str, Any]]] = None,
    benchmarks: Iterable[str] = ("b1", "b2"),
    reps: int = 6,
    base_ns: float = 1000.0,
) -> Tuple[Database, int, List[int]]:
    """Create/open a SQLite DB at ``db_path``, register one project, and seed commits + runs."""
    db = Database(str(db_path))
    pid = db.register_project(
        name=project_name,
        repo_url=repo_url,
        build_cmd="",
        adapter=adapter,
        config_toml="",
    )
    if commits is None:
        commits = [
            {
                "sha": f"sha{i}" * 4,
                "short_sha": f"sha{i}",
                "author_date": "2026-01-01",
                "subject": f"commit {i}",
                "run_started_utc": f"2026-01-01T10:{i:02d}:00+00:00",
                "run_finished_utc": f"2026-01-01T10:{i:02d}:30+00:00",
                "base_ns": base_ns + i,
            }
            for i in range(3)
        ]

    ids: List[int] = []
    bench_list = tuple(benchmarks)
    bulk_rows: List[Tuple[int, str, int, str, float]] = []
    for idx, c in enumerate(commits):
        short_sha = c["short_sha"]
        cid = db.insert_commit(
            project_id=pid,
            sha=c.get("sha", short_sha * 2),
            short_sha=short_sha,
            author_date=c.get("author_date", "2026-01-01"),
            subject=c.get("subject", f"commit {short_sha}"),
            build_ok=c.get("build_ok", True),
            build_seconds=c.get("build_seconds", 1.0),
            cpu_model=c.get("cpu_model", "test"),
            rustc_version=c.get("rustc_version", "n/a"),
            run_started_utc=c.get("run_started_utc", ""),
            run_finished_utc=c.get("run_finished_utc", ""),
        )
        c_base = float(c.get("base_ns", base_ns + idx))
        for bench in bench_list:
            for r in range(1, reps + 1):
                bulk_rows.append((cid, bench, r, "", c_base + r))
        ids.append(cid)
    if bulk_rows:
        db.insert_runs_bulk(bulk_rows)
    return db, pid, ids


def make_test_client(db_path: Path):
    """Build an isolated FastAPI TestClient against ``db_path`` (skips if httpx is absent)."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from server.app import create_app

    return TestClient(create_app(db_path=str(db_path)))
