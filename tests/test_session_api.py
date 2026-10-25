"""
tests/test_session_api.py
Session-break accounting in core.session and its exposure through the dashboard API.
"""

import pytest

from core.db import Database
from core.session import SESSION_BREAK_MIN, is_session_break, session_gap_minutes


def test_is_session_break_threshold():
    assert not is_session_break(None)
    assert not is_session_break(SESSION_BREAK_MIN)       # boundary is exclusive
    assert is_session_break(SESSION_BREAK_MIN + 0.1)
    assert not is_session_break(3.0)


def test_regressor_reexports_shared_helper():
    import regressor
    assert regressor.session_gap_minutes is session_gap_minutes
    assert regressor.SESSION_BREAK_MIN == SESSION_BREAK_MIN


@pytest.fixture
def api_client(tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from server.app import create_app

    db_path = tmp_path / "t.db"
    db = Database(str(db_path))
    pid = db.register_project(name="demo", repo_url="https://example.invalid/demo.git",
                              build_cmd="", adapter="PyMicroAdapter", config_toml="")
    # c0 -> c1: 2 min gap (same session); c1 -> c2: 201 min gap (session break)
    windows = [("aaaaaaa", "2026-01-01T10:00:00+00:00", "2026-01-01T10:10:00+00:00"),
               ("bbbbbbb", "2026-01-01T10:12:00+00:00", "2026-01-01T10:20:00+00:00"),
               ("ccccccc", "2026-01-01T13:41:00+00:00", "2026-01-01T13:50:00+00:00")]
    for sha, start, end in windows:
        cid = db.insert_commit(project_id=pid, sha=sha * 2, short_sha=sha, author_date="2026-01-01",
                               subject=f"commit {sha}", build_ok=True, build_seconds=1.0,
                               cpu_model="test", rustc_version="n/a",
                               run_started_utc=start, run_finished_utc=end)
        for i in range(5):
            db.insert_run(commit_id=cid, benchmark="b", rep_index=i + 1,
                          sample_file_path="", median_ns=1000.0 + i)
    return TestClient(create_app(db_path=str(db_path)))


def test_series_reports_gap_and_break(api_client):
    data = api_client.get("/api/projects/demo/series").json()
    pts = data["series"]["b"]
    assert data["session_break_min"] == SESSION_BREAK_MIN
    assert [p["session_gap_min"] for p in pts] == [None, 2.0, 201.0]
    assert [p["session_break"] for p in pts] == [False, False, True]


def test_distribution_reports_session_context(api_client):
    s = api_client.get("/api/commits/ccccccc/distribution").json()
    assert s["session"]["prev_short_sha"] == "bbbbbbb"
    assert s["session"]["gap_min"] == 201.0
    assert s["session"]["session_break"] is True
    assert s["commit"]["run_started_utc"].startswith("2026-01-01T13:41")

    first = api_client.get("/api/commits/aaaaaaa/distribution").json()
    assert first["session"]["prev_short_sha"] is None
    assert first["session"]["gap_min"] is None
