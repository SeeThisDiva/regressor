"""
tests/test_summary_reporting.py
Tests for publishable summary metrics, Wilson CI, triage overlay, flamegraph/issue
sanitization, REST `/summary`, and `regressor.py summary` CLI output.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from scipy import stats

import regressor
from core.db import Database
from core.report import (
    compute_project_summary,
    compute_summary_from_records,
    discover_flamegraphs,
    load_triage_entries,
    render_summary_markdown,
    sanitize_flamegraph_name,
    sanitize_issue_url,
    wilson_ci,
)
from tests.helpers import make_test_client, seed_project_db

ROOT = Path(__file__).resolve().parent.parent
STUDY1_DATA = ROOT / "data" / "regex_history.json.gz"


@pytest.mark.parametrize("k,n", [(0, 5), (5, 5), (3, 4), (1, 20), (4, 21), (0, 100), (12, 25)])
def test_wilson_ci_matches_scipy(k: int, n: int):
    expected = stats.binomtest(k, n).proportion_ci(confidence_level=0.95, method="wilson")
    assert wilson_ci(k, n, 0.95) == [round(100.0 * expected.low, 2), round(100.0 * expected.high, 2)]


def test_wilson_ci_zero_denominator_and_validation():
    assert wilson_ci(0, 0) == [0.0, 100.0]
    with pytest.raises(ValueError):
        wilson_ci(6, 5)
    with pytest.raises(ValueError):
        wilson_ci(-1, 5)
    with pytest.raises(ValueError):
        wilson_ci(1, 5, level=1.5)


def test_url_and_flamegraph_sanitization():
    assert sanitize_issue_url("https://github.com/rust-lang/regex/issues/1234") == (
        "https://github.com/rust-lang/regex/issues/1234"
    )
    assert sanitize_issue_url("  http://example.invalid/issue/1  ") == "http://example.invalid/issue/1"
    for bad_url in ("javascript:alert(1)", "data:text/html,<script>", "file:///etc/passwd", "https://bad url/1", "", None):
        assert sanitize_issue_url(bad_url) is None

    assert sanitize_flamegraph_name("flamegraph_diff.svg") == "flamegraph_diff.svg"
    assert sanitize_flamegraph_name("assets/flamegraphs/flamegraph_diff.svg") == "flamegraph_diff.svg"
    assert sanitize_flamegraph_name("/flamegraphs/flamegraph_diff.svg") == "flamegraph_diff.svg"
    for bad_fg in ("../secret.svg", "assets/flamegraphs/../secret.svg", "other/dir/secret.svg", "foo.png", "bad name.svg", "", None):
        assert sanitize_flamegraph_name(bad_fg) is None


def test_compute_summary_handles_mixed_triage_and_subthreshold_layout(tmp_path: Path):
    assets_dir = tmp_path / "flamegraphs"
    assets_dir.mkdir()
    (assets_dir / "flamegraph_diff_aaaa111.svg").write_text("<svg></svg>", encoding="utf-8")
    (assets_dir / "flamegraph_diff_cccc333.svg").write_text("<svg></svg>", encoding="utf-8")

    commits = [
        {"id": 1, "sha": "000000000000", "short_sha": "0000000"},
        {"id": 2, "sha": "aaaa11111111", "short_sha": "aaaa111"},
        {"id": 3, "sha": "bbbb22222222", "short_sha": "bbbb222"},
        {"id": 4, "sha": "cccc33333333", "short_sha": "cccc333"},
        {"id": 5, "sha": "dddd44444444", "short_sha": "dddd444"},
    ]
    comparisons = [
        {
            "base_sha": "0000000",
            "cand_commit_id": 2,
            "cand_sha": "aaaa111",
            "benchmark": "b_confirmed",
            "shift_pct": 9.5,
            "p_value": 1e-7,
            "noise_floor_pct": 2.0,
            "verdict": "flag",
            "fdr_significant": True,
            "resolution_status": "unreviewed",
            "resolution_note": "",
            "session_gap_min": 1.0,
        },
        {
            "base_sha": "aaaa111",
            "cand_commit_id": 3,
            "cand_sha": "bbbb222",
            "benchmark": "b_fp",
            "shift_pct": 4.2,
            "p_value": 2e-6,
            "noise_floor_pct": 1.5,
            "verdict": "flag",
            "fdr_significant": True,
            "resolution_status": "unreviewed",
            "resolution_note": "",
            "session_gap_min": 2.0,
        },
        {
            "base_sha": "bbbb222",
            "cand_commit_id": 4,
            "cand_sha": "cccc333",
            "benchmark": "b_layout",
            "shift_pct": 2.6,
            "p_value": 1e-6,
            "noise_floor_pct": 1.2,
            "verdict": "flag",
            "fdr_significant": True,
            "resolution_status": "unreviewed",
            "resolution_note": "",
            "session_gap_min": 0.5,
        },
        {
            "base_sha": "cccc333",
            "cand_commit_id": 5,
            "cand_sha": "dddd444",
            "benchmark": "b_unrev",
            "shift_pct": 5.1,
            "p_value": 3e-5,
            "noise_floor_pct": 2.1,
            "verdict": "flag",
            "fdr_significant": True,
            "resolution_status": "unreviewed",
            "resolution_note": "",
            "session_gap_min": 0.5,
        },
        {
            "base_sha": "aaaa111",
            "cand_commit_id": 3,
            "cand_sha": "bbbb222",
            "benchmark": "b_confirmed",
            "shift_pct": 1.8,
            "p_value": 0.002,
            "noise_floor_pct": 4.0,
            "verdict": "ok",
            "fdr_significant": False,
            "resolution_status": "unreviewed",
            "resolution_note": "",
            "session_gap_min": 2.0,
        },
    ]
    triage_file = tmp_path / "demo.triage.json"
    triage_file.write_text(
        json.dumps([
            {
                "benchmark": "b_confirmed",
                "commit": "aaaa11111111",
                "status": "confirmed",
                "note": "Verified +9.5% slowdown via 30-pair interleaved A/B.",
                "issue_url": "https://github.com/rust-lang/regex/issues/9999",
                "flamegraph": "flamegraph_diff_aaaa111.svg",
            },
            {
                "benchmark": "b_fp",
                "commit": "bbbb222",
                "status": "false_positive",
                "note": "Did not reproduce.",
                "issue_url": "javascript:alert(1)",
            },
            {
                "benchmark": "b_layout",
                "commit": "cccc333",
                "status": "layout_artifact",
                "note": "LTO binary-layout reordering (+0 insns).",
            },
            {
                # Sub-threshold entry (unflagged comparison) triaged separately as layout_artifact
                "benchmark": "b_confirmed",
                "commit": "bbbb222",
                "status": "layout_artifact",
                "note": "Sub-threshold layout shift.",
            },
        ]),
        encoding="utf-8",
    )

    triage_entries = load_triage_entries("demo", projects_dir=tmp_path, assets_dir=assets_dir)
    fgs = discover_flamegraphs(assets_dir=assets_dir)
    summary = compute_summary_from_records(
        project="demo",
        commits=commits,
        comparisons=comparisons,
        triage_entries=triage_entries,
        benchmarks=["b_confirmed", "b_fp", "b_layout", "b_unrev"],
        flamegraphs=fgs,
        study="db",
    )

    assert summary["commits_analyzed"] == 5
    assert summary["benchmarks_count"] == 4
    assert summary["comparisons"] == 5
    assert summary["regressions_flagged"] == 4
    assert summary["confirmed_real"] == 1
    assert summary["false_positives"] == 1
    assert summary["layout_artifacts"] == 2
    assert summary["unreviewed"] == 1
    assert summary["flagged_breakdown"] == {
        "confirmed": 1,
        "false_positive": 1,
        "layout_artifact": 1,
        "unreviewed": 1,
    }
    assert summary["fp_rate"] == 0.25
    assert summary["fp_rate_pct"] == 25.0
    assert summary["fp_rate_wilson_ci95_pct"] == wilson_ci(1, 4)
    assert summary["upstream_issue_urls"] == ["https://github.com/rust-lang/regex/issues/9999"]
    assert len(summary["upstream_issues"]) == 1
    assert len(summary["flamegraphs"]) == 2


def test_compute_summary_zero_flagged_edge_case():
    summary = compute_summary_from_records(
        project="demo",
        commits=[{"id": 1, "sha": "aaaa1111", "short_sha": "aaaa111"}],
        comparisons=[],
        triage_entries=[],
        benchmarks=["b1"],
        flamegraphs=[],
    )
    assert summary["regressions_flagged"] == 0
    assert summary["fp_rate"] is None
    assert summary["fp_rate_pct"] is None
    assert summary["fp_rate_wilson_ci95_pct"] == [0.0, 100.0]
    assert summary["upstream_issues"] == []


def test_compute_summary_counts_subthreshold_confirmed_matching_unflagged_comparison():
    commits = [
        {"id": 1, "sha": "aaaa11110000", "short_sha": "aaaa111"},
        {"id": 2, "sha": "bbbb22220000", "short_sha": "bbbb222"},
    ]
    comparisons = [
        {
            "base_sha": "aaaa111",
            "cand_commit_id": 2,
            "cand_sha": "bbbb222",
            "benchmark": "b1",
            "shift_pct": 2.9,
            "p_value": 0.002,
            "noise_floor_pct": 5.0,
            "verdict": "ok",
            "fdr_significant": False,
            "resolution_status": "unreviewed",
            "resolution_note": "",
            "session_gap_min": 1.0,
        },
    ]
    triage = [
        {
            "benchmark": "b1",
            "commit": "bbbb222",
            "status": "confirmed",
            "note": "Sub-threshold shift confirmed via 30-pair interleaved A/B.",
            "issue_url": "https://github.com/rust-lang/regex/issues/7777",
        },
    ]
    summary = compute_summary_from_records(
        project="demo",
        commits=commits,
        comparisons=comparisons,
        triage_entries=triage,
        benchmarks=["b1"],
        flamegraphs=[],
    )
    assert summary["regressions_flagged"] == 0
    assert summary["confirmed_real"] == 1
    assert summary["upstream_issue_urls"] == ["https://github.com/rust-lang/regex/issues/7777"]
    assert len(summary["upstream_issues"]) == 1


def test_compute_summary_ignores_triage_for_benchmarks_not_in_study():
    commits = [
        {"id": 1, "sha": "aaaa11110000", "short_sha": "aaaa111"},
        {"id": 2, "sha": "bbbb22220000", "short_sha": "bbbb222"},
    ]
    comparisons = [
        {
            "base_sha": "aaaa111",
            "cand_commit_id": 2,
            "cand_sha": "bbbb222",
            "benchmark": "legacy_bench",
            "shift_pct": 4.0,
            "p_value": 1e-6,
            "noise_floor_pct": 1.0,
            "verdict": "flag",
            "fdr_significant": True,
            "resolution_status": "unreviewed",
            "resolution_note": "",
            "session_gap_min": 1.0,
        },
    ]
    triage = [
        {
            "benchmark": "legacy_bench",
            "commit": "bbbb222",
            "status": "false_positive",
            "note": "Legacy bench FP.",
        },
        {
            # Same commit, different benchmark that was NOT run in this study (e.g. Study 3 rebar_* vs Study 2)
            "benchmark": "rebar_only_bench",
            "commit": "bbbb222",
            "status": "confirmed",
            "note": "Confirmed only on rebar_only_bench.",
            "issue_url": "https://github.com/rust-lang/regex/issues/8888",
        },
        {
            "benchmark": "rebar_only_other",
            "commit": "bbbb222",
            "status": "layout_artifact",
            "note": "Layout shift only on rebar_only_other.",
        },
    ]
    summary = compute_summary_from_records(
        project="demo",
        commits=commits,
        comparisons=comparisons,
        triage_entries=triage,
        benchmarks=["legacy_bench"],
        flamegraphs=[],
    )
    assert summary["regressions_flagged"] == 1
    assert summary["false_positives"] == 1
    assert summary["confirmed_real"] == 0
    assert summary["layout_artifacts"] == 0
    assert summary["upstream_issues"] == []


def test_render_summary_markdown_escapes_html_and_table_injection():
    summary = {
        "project": "bad|proj`<script>alert(1)</script>",
        "study": "db",
        "commits_analyzed": 10,
        "benchmarks_count": 2,
        "comparisons": 18,
        "flagged_pre_fdr": 1,
        "regressions_flagged": 1,
        "confirmed_real": 1,
        "false_positives": 0,
        "layout_artifacts": 0,
        "unreviewed": 0,
        "fp_rate": 0.0,
        "fp_rate_pct": 0.0,
        "fp_rate_wilson_ci95_pct": [0.0, 79.35],
        "upstream_issue_urls": ["https://example.invalid/issue/1"],
        "upstream_issues": [{
            "issue_url": "https://example.invalid/issue/1",
            "commit": "abc1234",
            "benchmark": "b|<img src=x>",
            "status": "confirmed",
            "note": "real",
        }],
        "flagged_items": [{
            "cand_sha": "abc1234",
            "benchmark": "b|<script>",
            "shift_pct": 8.0,
            "p_value": 1e-6,
            "noise_floor_pct": 2.0,
            "status": "confirmed",
            "note": "note|with`pipe<script>",
        }],
    }
    md = render_summary_markdown(summary)
    assert "<script>" not in md
    assert "<img" not in md
    assert "&lt;script&gt;" in md
    assert "\\|" in md
    assert "Wilson 95% CI" in md
    assert "https://example.invalid/issue/1" in md


@pytest.mark.skipif(not STUDY1_DATA.exists(), reason="data/regex_history.json.gz not present")
def test_cli_summary_on_study1_json_markdown_and_text(tmp_path: Path, monkeypatch, capsys):
    db_path = str(tmp_path / "sum.db")
    for argv in (
        ["regressor", "--db", db_path, "import-data", str(STUDY1_DATA)],
        ["regressor", "--db", db_path, "batch", "regex", "--verify-legacy"],
    ):
        monkeypatch.setattr(sys, "argv", argv)
        assert regressor.main() == 0
    capsys.readouterr()

    # 1. Text + markdown output
    md_out = tmp_path / "summary.md"
    monkeypatch.setattr(sys, "argv", ["regressor", "--db", db_path, "summary", "regex", "--markdown", str(md_out)])
    assert regressor.main() == 0
    text_out = capsys.readouterr().out
    assert "Commits analyzed:          27" in text_out
    assert "Regressions flagged (FDR): 5" in text_out
    assert "5/5 (100.0%, 95% Wilson CI [56.55%, 100.00%])" in text_out
    assert md_out.is_file()
    md_text = md_out.read_text(encoding="utf-8")
    assert "27 commits" in md_text and "56.55%, 100.00%" in md_text

    # 2. Pure JSON output
    monkeypatch.setattr(sys, "argv", ["regressor", "--db", db_path, "summary", "regex", "--json"])
    assert regressor.main() == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["commits_analyzed"] == 27
    assert parsed["comparisons"] == 78
    assert parsed["regressions_flagged"] == 5
    assert parsed["confirmed_real"] == 0
    assert parsed["false_positives"] == 5
    assert parsed["fp_rate"] == 1.0
    assert parsed["fp_rate_wilson_ci95_pct"] == [56.55, 100.0]
    assert parsed["layout_artifacts"] == 0

    # 3. Direct DB helper agrees
    assert compute_project_summary(Database(db_path), "regex")["regressions_flagged"] == 5


def test_api_summary_endpoint_and_validation(tmp_path: Path):
    db_path = tmp_path / "api_sum.db"
    db, pid, ids = seed_project_db(
        db_path,
        project_name="demo",
        commits=[
            {"short_sha": "aaaa111", "base_ns": 1000.0},
            {"short_sha": "bbbb222", "base_ns": 1200.0},
        ],
        benchmarks=("b1",),
        reps=6,
    )
    db.insert_comparison(
        project_id=pid,
        base_commit_id=ids[0],
        cand_commit_id=ids[1],
        benchmark="b1",
        p_value=0.002,
        shift_pct=20.0,
        noise_floor_pct=1.0,
        verdict="flag",
        fdr_significant=True,
        resolution_note="real slowdown",
        resolution_status="confirmed",
    )

    client = make_test_client(db_path)
    r = client.get("/api/projects/demo/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["commits_analyzed"] == 2
    assert body["comparisons"] == 1
    assert body["regressions_flagged"] == 1
    assert body["confirmed_real"] == 1
    assert body["false_positives"] == 0
    assert body["fp_rate_wilson_ci95_pct"] == [0.0, 79.35]

    assert client.get("/api/projects/missing/summary").status_code == 404
    assert client.get("/api/projects/-bad/summary").status_code == 400
    assert client.get("/api/projects/demo/summary?study=no_such_study").status_code == 404
