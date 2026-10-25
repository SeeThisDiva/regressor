"""
tests/test_stage2_data.py
Data layer, API and reproduction guarantees added in Stage 2.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

import regressor
from core.db import Database

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "regex_history.json.gz"


def _seed(db, n_commits=3, reps=6):
    pid = db.register_project(name="demo", repo_url="", build_cmd="", adapter="PyMicroAdapter", config_toml="")
    ids = []
    for i in range(n_commits):
        cid = db.insert_commit(project_id=pid, sha=f"sha{i}" * 4, short_sha=f"sha{i}", author_date="2026-01-01",
                               subject=f"commit {i}", build_ok=True, build_seconds=1.0,
                               run_started_utc=f"2026-01-01T10:{i:02d}:00+00:00",
                               run_finished_utc=f"2026-01-01T10:{i:02d}:30+00:00")
        db.insert_runs_bulk((cid, b, r, "", 1000.0 + r + i) for b in ("b1", "b2") for r in range(1, reps + 1))
        ids.append(cid)
    return pid, ids


def test_reinserting_commits_and_runs_is_idempotent(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    pid, ids = _seed(db)
    again = db.insert_commit(project_id=pid, sha="sha0" * 4, short_sha="sha0", author_date="x", subject="renamed",
                             build_ok=True, build_seconds=2.0)
    db.insert_runs_bulk([(ids[0], "b1", 1, "", 5555.0)])
    assert again == ids[0]
    assert len(db.get_project_commits(pid)) == 3
    runs = db.get_project_runs(pid)
    assert len(runs[(ids[0], "b1")]) == 6 and runs[(ids[0], "b1")][0] == 5555.0   # updated, not duplicated


def test_bulk_runs_match_per_commit_query(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    pid, ids = _seed(db)
    bulk = db.get_project_runs(pid)
    for cid in ids:
        for b in ("b1", "b2"):
            assert bulk[(cid, b)] == db.get_commit_runs(cid, b)
    assert db.get_project_benchmarks(pid) == ["b1", "b2"]


def test_dedupe_repairs_database_that_already_has_duplicates(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT UNIQUE, repo_url TEXT, build_cmd TEXT, adapter TEXT, config_toml TEXT);
        CREATE TABLE commits (id INTEGER PRIMARY KEY, project_id INTEGER, sha TEXT, short_sha TEXT, author_date TEXT, subject TEXT,
            build_ok BOOLEAN, build_seconds REAL, cpu_model TEXT, rustc_version TEXT, run_started_utc TEXT, run_finished_utc TEXT);
        CREATE TABLE runs (id INTEGER PRIMARY KEY, commit_id INTEGER, benchmark TEXT, rep_index INTEGER, sample_file_path TEXT,
            median_ns REAL, pmu_json TEXT);
        INSERT INTO projects VALUES (1,'p','','','A','');
        INSERT INTO commits (project_id, sha, short_sha) VALUES (1,'aaa','aaa'),(1,'aaa','aaa');
        INSERT INTO runs (commit_id, benchmark, rep_index, median_ns) VALUES (1,'b',1,10.0),(2,'b',1,10.0),(1,'b',2,11.0);
    """)
    conn.commit(); conn.close()
    db = Database(str(path))                      # warns, does not crash
    assert db.dedupe() == {"commits_removed": 1, "runs_removed": 0}
    with db.get_conn() as c:
        assert c.execute("SELECT COUNT(*) FROM commits").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
        names = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "uq_commits_project_sha" in names


@pytest.fixture
def client(tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from server.app import create_app
    db_path = tmp_path / "api.db"
    _seed(Database(str(db_path)))
    return TestClient(create_app(db_path=str(db_path)))


def test_two_apps_do_not_share_state(tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from server.app import create_app
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    _seed(Database(str(a)), n_commits=3)
    _seed(Database(str(b)), n_commits=5)
    ca, cb = TestClient(create_app(db_path=str(a))), TestClient(create_app(db_path=str(b)))
    assert ca.get("/api/projects").json()[0]["total_commits"] == 3
    assert cb.get("/api/projects").json()[0]["total_commits"] == 5
    assert ca.get("/api/projects").json()[0]["total_commits"] == 3     # still 3 after b was created


def test_series_does_not_regress_to_one_query_per_commit(client, monkeypatch):
    opened = []
    real = sqlite3.connect
    monkeypatch.setattr("core.db.sqlite3.connect", lambda *a, **k: (opened.append(1), real(*a, **k))[1])
    assert client.get("/api/projects/demo/series").status_code == 200
    assert len(opened) <= 8, f"{len(opened)} connections for one /series request (was 86 before Stage 2)"


def test_sha_lookup_is_not_a_wildcard_and_needs_a_real_prefix(client):
    assert client.get("/api/commits/sha0/distribution").status_code == 200
    assert client.get("/api/commits/%25%25%25%25/distribution").status_code == 404   # '%%%%' used to match anything
    assert client.get("/api/commits/sh/distribution").status_code == 400


def test_cors_is_not_wildcard_with_credentials(client):
    r = client.get("/api/projects", headers={"Origin": "https://evil.example"})
    assert r.headers.get("access-control-allow-origin") is None
    assert r.headers.get("access-control-allow-credentials") is None


def test_importing_server_module_has_no_filesystem_side_effect(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import importlib

    import server.app as m
    importlib.reload(m)
    assert not (ROOT / "regressor.db.sentinel").exists()
    assert list(tmp_path.iterdir()) == []


# ---------- reproduction of the headline study, runnable in CI ----------

@pytest.mark.skipif(not DATA.exists(), reason="data/regex_history.json.gz not present")
def test_original_study_reproduces_from_portable_data(tmp_path, monkeypatch, capsys):
    dbp = str(tmp_path / "repro.db")
    for argv in (["regressor", "--db", dbp, "import-data", str(DATA)],
                 ["regressor", "--db", dbp, "import-data", str(DATA)],            # idempotent
                 ["regressor", "--db", dbp, "batch", "regex", "--verify-legacy"]):
        monkeypatch.setattr(sys, "argv", argv)
        assert regressor.main() == 0
    out = capsys.readouterr().out
    assert "Total Pairwise Tests:      78" in out and "Flagged Post-FDR (α=0.05): 5" in out


def test_triage_notes_are_data_not_code():
    notes = regressor._load_triage("regex")
    assert len(notes) == 5 and notes[("compile_moderate", "0a446ec")][1] == "false_positive"
    assert regressor._load_triage("no-such-project") == {}
