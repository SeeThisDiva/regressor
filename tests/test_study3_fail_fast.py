"""
tests/test_study3_fail_fast.py
Tests verifying fail-fast behavior (clear error naming data/regex_study3_history.json.gz,
no traceback, and no side-effect files/directories created) when Study 3 raw directories
or working SQLite DB are absent.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import List

import pytest

ROOT = Path(__file__).resolve().parent.parent
ANALYZE_STUDY3 = ROOT / "noise-bench" / "harness" / "analyze_study3.py"
RUN_STUDY3 = ROOT / "noise-bench" / "harness" / "run_study3.py"
PORTABLE_STUDY3_DATA = "data/regex_study3_history.json.gz"


def _run_harness_script(script: Path, args: List[str]) -> subprocess.CompletedProcess[str]:
    """Execute a harness CLI script under the active Python interpreter."""
    return subprocess.run(
        [sys.executable, "-B", str(script), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _load_module(name: str, path: Path):
    """Import a standalone harness script by path without modifying sys.path."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_analyze_study3_fails_fast_when_all_raw_inputs_missing(tmp_path: Path) -> None:
    db_path = tmp_path / "missing_dir" / "study3.db"
    results_dir = tmp_path / "study3_commits"
    baseline_dir = tmp_path / "study3_baseline"
    out_json = tmp_path / "out" / "study3_analysis.json"

    proc = _run_harness_script(
        ANALYZE_STUDY3,
        [
            "--db",
            str(db_path),
            "--results-dir",
            str(results_dir),
            "--baseline-dir",
            str(baseline_dir),
            "--out",
            str(out_json),
        ],
    )
    assert proc.returncode == 1
    assert "Traceback" not in proc.stdout
    assert "Traceback" not in proc.stderr
    assert PORTABLE_STUDY3_DATA in proc.stderr
    assert not db_path.parent.exists()
    assert not results_dir.exists()
    assert not baseline_dir.exists()
    assert not out_json.exists()


def test_analyze_study3_default_paths_fail_fast_without_creating_db() -> None:
    default_study3_dir = ROOT / "noise-bench" / "results" / "study3"
    assert not default_study3_dir.exists()

    proc = _run_harness_script(ANALYZE_STUDY3, [])
    assert proc.returncode == 1
    assert "Traceback" not in proc.stdout
    assert "Traceback" not in proc.stderr
    assert PORTABLE_STUDY3_DATA in proc.stderr
    assert not default_study3_dir.exists()


@pytest.mark.parametrize("case", ["missing_results_dir", "missing_baseline_dir"])
def test_analyze_study3_fails_fast_on_partial_raw_inputs(tmp_path: Path, case: str) -> None:
    db_path = tmp_path / "study3.db"
    db_path.write_text("", encoding="utf-8")
    results_dir = tmp_path / "study3_commits"
    baseline_dir = tmp_path / "study3_baseline"
    if case == "missing_baseline_dir":
        results_dir.mkdir()

    proc = _run_harness_script(
        ANALYZE_STUDY3,
        [
            "--db",
            str(db_path),
            "--results-dir",
            str(results_dir),
            "--baseline-dir",
            str(baseline_dir),
        ],
    )
    assert proc.returncode == 1
    assert "Traceback" not in proc.stdout
    assert "Traceback" not in proc.stderr
    assert PORTABLE_STUDY3_DATA in proc.stderr


def test_run_study3_default_paths_fail_fast_without_creating_dirs() -> None:
    default_study3_dir = ROOT / "noise-bench" / "results" / "study3"
    default_commits_dir = ROOT / "noise-bench" / "results" / "study3_commits"
    assert not default_study3_dir.exists()
    assert not default_commits_dir.exists()

    proc = _run_harness_script(RUN_STUDY3, [])
    assert proc.returncode == 1
    assert "Traceback" not in proc.stdout
    assert "Traceback" not in proc.stderr
    assert PORTABLE_STUDY3_DATA in proc.stderr
    assert not default_study3_dir.exists()
    assert not default_commits_dir.exists()


@pytest.mark.parametrize(
    "mode",
    ["explicit_resume", "start_index", "existing_checkpoint", "existing_db_only"],
)
def test_run_study3_resume_paths_fail_fast(tmp_path: Path, mode: str) -> None:
    db_path = tmp_path / "study3" / "study3.db"
    results_dir = tmp_path / "study3_commits"
    checkpoint = tmp_path / "study3" / "checkpoint.json"
    log_dir = tmp_path / "logs"

    extra_args: List[str] = []
    if mode == "explicit_resume":
        extra_args = ["--resume"]
    elif mode == "start_index":
        extra_args = ["--start-index", "5"]
    elif mode == "existing_checkpoint":
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_text('{"last_completed_index": 4}', encoding="utf-8")
    elif mode == "existing_db_only":
        db_path.parent.mkdir(parents=True)
        db_path.write_text("", encoding="utf-8")

    proc = _run_harness_script(
        RUN_STUDY3,
        [
            "--db",
            str(db_path),
            "--results-dir",
            str(results_dir),
            "--checkpoint",
            str(checkpoint),
            "--log-dir",
            str(log_dir),
            *extra_args,
        ],
    )
    assert proc.returncode == 1
    assert "Traceback" not in proc.stdout
    assert "Traceback" not in proc.stderr
    assert PORTABLE_STUDY3_DATA in proc.stderr
    assert not results_dir.exists()
    assert not log_dir.exists()


def test_run_study3_validate_resume_state_allows_fresh_and_complete(tmp_path: Path) -> None:
    run_study3 = _load_module("study3_driver_unit", RUN_STUDY3)
    parser = run_study3.build_parser()

    fresh_args = parser.parse_args(
        [
            "--db",
            str(tmp_path / "fresh" / "study3.db"),
            "--results-dir",
            str(tmp_path / "fresh_commits"),
            "--checkpoint",
            str(tmp_path / "fresh" / "checkpoint.json"),
            "--log-dir",
            str(tmp_path / "fresh_logs"),
        ]
    )
    run_study3.validate_resume_state(fresh_args)

    ready_db = tmp_path / "ready" / "study3.db"
    ready_db.parent.mkdir(parents=True)
    ready_db.write_text("", encoding="utf-8")
    ready_results = tmp_path / "ready_commits"
    ready_results.mkdir()

    resume_args = parser.parse_args(
        [
            "--db",
            str(ready_db),
            "--results-dir",
            str(ready_results),
            "--checkpoint",
            str(tmp_path / "ready" / "checkpoint.json"),
            "--log-dir",
            str(tmp_path / "ready_logs"),
            "--resume",
        ]
    )
    run_study3.validate_resume_state(resume_args)
