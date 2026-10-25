"""
core/db.py
SQLite persistence layer: projects, commits, per-run medians and comparisons.
"""

import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

MIN_SHA_PREFIX = 4


def resolve_commit_prefix(commits: Sequence[Any], prefix: str) -> Tuple[Optional[Any], Optional[str]]:
    """Resolve a SHA prefix against a project's commits. Returns (commit, None) on a unique match,
    or (None, error message) when the prefix is too short, matches nothing, or is ambiguous.
    Silently taking the first of several matches would compare the wrong commit."""
    if not prefix or len(prefix) < MIN_SHA_PREFIX:
        return None, f"SHA prefix {prefix!r} is too short (need at least {MIN_SHA_PREFIX} characters)"
    matches = [c for c in commits if c["sha"].startswith(prefix) or c["short_sha"].startswith(prefix)]
    if not matches:
        return None, f"commit {prefix!r} not found"
    if len(matches) > 1:
        shas = ", ".join(c["short_sha"] for c in matches[:5])
        return None, f"SHA prefix {prefix!r} is ambiguous ({len(matches)} matches: {shas}); use more characters"
    return matches[0], None

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE,
  repo_url TEXT,
  build_cmd TEXT,
  adapter TEXT,
  config_toml TEXT
);

CREATE TABLE IF NOT EXISTS commits (
  id INTEGER PRIMARY KEY,
  project_id INTEGER,
  sha TEXT,
  short_sha TEXT,
  author_date TEXT,
  subject TEXT,
  build_ok BOOLEAN,
  build_seconds REAL,
  cpu_model TEXT,
  rustc_version TEXT,
  run_started_utc TEXT,
  run_finished_utc TEXT,
  FOREIGN KEY(project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY,
  commit_id INTEGER,
  benchmark TEXT,
  rep_index INTEGER,
  sample_file_path TEXT,
  median_ns REAL,
  pmu_json TEXT,
  FOREIGN KEY(commit_id) REFERENCES commits(id)
);

CREATE TABLE IF NOT EXISTS comparisons (
  id INTEGER PRIMARY KEY,
  project_id INTEGER,
  base_commit_id INTEGER,
  cand_commit_id INTEGER,
  benchmark TEXT,
  p_value REAL,
  shift_pct REAL,
  noise_floor_pct REAL,
  verdict TEXT,
  fdr_significant BOOLEAN,
  resolution_note TEXT,
  resolution_status TEXT,  -- 'unreviewed' | 'confirmed' | 'false_positive'
  canary_status TEXT DEFAULT 'OK',
  pmu_status TEXT DEFAULT 'UNAVAILABLE',
  FOREIGN KEY(project_id) REFERENCES projects(id),
  FOREIGN KEY(base_commit_id) REFERENCES commits(id),
  FOREIGN KEY(cand_commit_id) REFERENCES commits(id)
);

CREATE INDEX IF NOT EXISTS idx_commits_sha ON commits(sha);
CREATE INDEX IF NOT EXISTS idx_runs_commit_bench ON runs(commit_id, benchmark);
CREATE INDEX IF NOT EXISTS idx_comparisons_proj ON comparisons(project_id);
"""


# Uniqueness makes imports idempotent: re-running import-legacy used to silently duplicate every
# commit and run. Created separately because an existing database may already contain duplicates.
UNIQUE_INDEXES = (
    ("uq_commits_project_sha", "commits(project_id, sha)"),
    ("uq_runs_commit_bench_rep", "runs(commit_id, benchmark, rep_index)"),
)

# Schema setup is a per-file, once-per-process job; the API used to repeat it on every request.
_INITIALIZED: set = set()


class Database:
    def __init__(self, db_path: str = "regressor.db"):
        self.db_path = str(db_path)
        p = Path(self.db_path)
        key = str(p.resolve())
        if key not in _INITIALIZED or not p.exists() or p.stat().st_size == 0:
            self.init_db()
            _INITIALIZED.add(key)

    @contextmanager
    def get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init_db(self):
        with self.get_conn() as conn:
            conn.executescript(SCHEMA)
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(comparisons)")}
            if "session_gap_min" not in cols:
                conn.execute("ALTER TABLE comparisons ADD COLUMN session_gap_min REAL")
            for name, target in UNIQUE_INDEXES:
                try:
                    conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {target}")
                except sqlite3.IntegrityError:
                    print(f"[regressor] warning: {name} not created, {self.db_path} already holds duplicate rows "
                          f"in {target.split('(')[0]}; run `regressor dedupe` once.", file=sys.stderr)

    def register_project(self, name: str, repo_url: str, build_cmd: str, adapter: str, config_toml: str) -> int:
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO projects (name, repo_url, build_cmd, adapter, config_toml)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    repo_url=excluded.repo_url,
                    build_cmd=excluded.build_cmd,
                    adapter=excluded.adapter,
                    config_toml=excluded.config_toml
            """, (name, repo_url, build_cmd, adapter, config_toml))
            return cur.lastrowid or self.get_project_id(name)

    def get_project_id(self, name: str) -> Optional[int]:
        with self.get_conn() as conn:
            row = conn.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()
            return row["id"] if row else None

    def insert_commit(
        self,
        project_id: int,
        sha: str,
        short_sha: str,
        author_date: str,
        subject: str,
        build_ok: bool,
        build_seconds: float,
        cpu_model: str = "unknown",
        rustc_version: str = "unknown",
        run_started_utc: str = "",
        run_finished_utc: str = ""
    ) -> int:
        with self.get_conn() as conn:
            existing = conn.execute("SELECT id FROM commits WHERE project_id = ? AND sha = ?",
                                    (project_id, sha)).fetchone()
            if existing:
                conn.execute("""
                    UPDATE commits SET short_sha=?, author_date=?, subject=?, build_ok=?, build_seconds=?,
                        cpu_model=?, rustc_version=?, run_started_utc=?, run_finished_utc=?
                    WHERE id = ?
                """, (short_sha, author_date, subject, build_ok, build_seconds, cpu_model,
                      rustc_version, run_started_utc, run_finished_utc, existing["id"]))
                return existing["id"]
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO commits (
                    project_id, sha, short_sha, author_date, subject,
                    build_ok, build_seconds, cpu_model, rustc_version,
                    run_started_utc, run_finished_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                project_id, sha, short_sha, author_date, subject,
                build_ok, build_seconds, cpu_model, rustc_version,
                run_started_utc, run_finished_utc
            ))
            return cur.lastrowid

    def insert_run(
        self,
        commit_id: int,
        benchmark: str,
        rep_index: int,
        sample_file_path: str,
        median_ns: float,
        pmu_metrics: Optional[Dict[str, Any]] = None
    ) -> int:
        pmu_json = json.dumps(pmu_metrics or {})
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(self._UPSERT_RUN, (commit_id, benchmark, rep_index, sample_file_path, median_ns, pmu_json))
            return cur.lastrowid

    _UPSERT_RUN = """
        INSERT INTO runs (commit_id, benchmark, rep_index, sample_file_path, median_ns, pmu_json)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(commit_id, benchmark, rep_index) DO UPDATE SET
            sample_file_path=excluded.sample_file_path, median_ns=excluded.median_ns, pmu_json=excluded.pmu_json
    """

    def insert_runs_bulk(self, rows: Iterable[Tuple[int, str, int, str, float]]) -> int:
        """rows: (commit_id, benchmark, rep_index, sample_file_path, median_ns). One transaction."""
        payload = [(c, b, r, f, m, "{}") for c, b, r, f, m in rows]
        with self.get_conn() as conn:
            conn.executemany(self._UPSERT_RUN, payload)
        return len(payload)

    def insert_comparison(
        self,
        project_id: int,
        base_commit_id: int,
        cand_commit_id: int,
        benchmark: str,
        p_value: float,
        shift_pct: float,
        noise_floor_pct: float,
        verdict: str,
        fdr_significant: bool,
        resolution_note: str = "",
        resolution_status: str = "unreviewed",
        canary_status: str = "NOT_RECORDED",
        pmu_status: str = "UNAVAILABLE",
        session_gap_min: Optional[float] = None,
    ) -> int:
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO comparisons (
                    project_id, base_commit_id, cand_commit_id, benchmark,
                    p_value, shift_pct, noise_floor_pct, verdict, fdr_significant,
                    resolution_note, resolution_status, canary_status, pmu_status,
                    session_gap_min
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                project_id, base_commit_id, cand_commit_id, benchmark,
                p_value, shift_pct, noise_floor_pct, verdict, fdr_significant,
                resolution_note, resolution_status, canary_status, pmu_status,
                session_gap_min,
            ))
            return cur.lastrowid

    def get_commit_runs(self, commit_id: int, benchmark: str) -> List[float]:
        with self.get_conn() as conn:
            rows = conn.execute("""
                SELECT median_ns FROM runs
                WHERE commit_id = ? AND benchmark = ?
                ORDER BY rep_index ASC
            """, (commit_id, benchmark)).fetchall()
            return [r["median_ns"] for r in rows]

    def get_project_runs(self, project_id: int) -> Dict[Tuple[int, str], List[float]]:
        """All per-run medians of a project in ONE query: {(commit_id, benchmark): [median_ns by rep]}."""
        out: Dict[Tuple[int, str], List[float]] = {}
        with self.get_conn() as conn:
            for r in conn.execute("""
                SELECT r.commit_id, r.benchmark, r.median_ns FROM runs r
                JOIN commits c ON r.commit_id = c.id
                WHERE c.project_id = ? ORDER BY r.commit_id, r.benchmark, r.rep_index
            """, (project_id,)):
                out.setdefault((r["commit_id"], r["benchmark"]), []).append(r["median_ns"])
        return out

    def get_project_benchmarks(self, project_id: int) -> List[str]:
        with self.get_conn() as conn:
            return [r["benchmark"] for r in conn.execute("""
                SELECT DISTINCT r.benchmark FROM runs r JOIN commits c ON r.commit_id = c.id
                WHERE c.project_id = ? ORDER BY r.benchmark
            """, (project_id,))]

    def project_summary(self, project_id: int) -> Dict[str, int]:
        with self.get_conn() as conn:
            row = conn.execute("""
                SELECT (SELECT COUNT(*) FROM commits WHERE project_id = :p) AS commits,
                       (SELECT COUNT(*) FROM comparisons WHERE project_id = :p) AS comparisons,
                       (SELECT COUNT(*) FROM comparisons WHERE project_id = :p
                            AND verdict = 'flag' AND fdr_significant) AS flags,
                       (SELECT COUNT(*) FROM comparisons WHERE project_id = :p
                            AND resolution_status = 'confirmed') AS confirmed
            """, {"p": project_id}).fetchone()
            return dict(row)

    def dedupe(self) -> Dict[str, int]:
        """Collapse duplicate commits (same project+sha, keeping the first) and duplicate runs."""
        with self.get_conn() as conn:
            dup = conn.execute("""
                SELECT id, (SELECT MIN(c2.id) FROM commits c2
                            WHERE c2.project_id = c.project_id AND c2.sha = c.sha) AS keep
                FROM commits c
            """).fetchall()
            moved = 0
            for r in dup:
                if r["id"] != r["keep"]:
                    conn.execute("DELETE FROM runs WHERE commit_id = ?", (r["id"],))
                    conn.execute("DELETE FROM commits WHERE id = ?", (r["id"],))
                    moved += 1
            runs = conn.execute("""
                DELETE FROM runs WHERE id NOT IN
                    (SELECT MIN(id) FROM runs GROUP BY commit_id, benchmark, rep_index)
            """).rowcount
        self.init_db()
        return {"commits_removed": moved, "runs_removed": runs}

    def get_project_commits(self, project_id: int) -> List[sqlite3.Row]:
        with self.get_conn() as conn:
            return conn.execute("""
                SELECT * FROM commits
                WHERE project_id = ?
                ORDER BY id ASC
            """, (project_id,)).fetchall()

    def get_project_comparisons(self, project_id: int) -> List[sqlite3.Row]:
        with self.get_conn() as conn:
            return conn.execute("""
                SELECT c.*,
                       b.short_sha AS base_sha,
                       k.short_sha AS cand_sha,
                       k.subject AS cand_subject
                FROM comparisons c
                JOIN commits b ON c.base_commit_id = b.id
                JOIN commits k ON c.cand_commit_id = k.id
                WHERE c.project_id = ?
                ORDER BY c.id ASC
            """, (project_id,)).fetchall()

    def clear_project_comparisons(self, project_id: int):
        with self.get_conn() as conn:
            conn.execute("DELETE FROM comparisons WHERE project_id = ?", (project_id,))

    def get_all_projects(self) -> List[sqlite3.Row]:
        with self.get_conn() as conn:
            return conn.execute("SELECT * FROM projects ORDER BY name ASC").fetchall()
