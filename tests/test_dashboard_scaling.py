"""
tests/test_dashboard_scaling.py
Tests for 25-benchmark dashboard scaling, multi-study dataset switching (Studies 1-3),
CI bands and triage status overlays, flamegraph/issue links, UI DOM safety, and static export.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List

import pytest

import regressor
from server.app import create_app, export_static_site
from tests.helpers import seed_project_db

ROOT = Path(__file__).resolve().parent.parent
STUDY1_DATA = ROOT / "data" / "regex_history.json.gz"
STUDY2_DATA = ROOT / "data" / "regex_study2_history.json.gz"
STUDY3_DATA = ROOT / "data" / "regex_study3_history.json.gz"


def _make_25_benchmarks() -> List[str]:
    return [
        "compile_moderate",
        "find_iter_userid",
        "is_match_status",
        *[f"rebar_bench_{i:02d}" for i in range(1, 23)],
    ]


def _make_study_fixture(path: Path, project: str, benchmarks: List[str], n_commits: int = 8) -> None:
    commits = []
    for idx in range(n_commits):
        sha = f"{idx + 1:07x}" + "0" * 33
        runs: Dict[str, List[float]] = {}
        for b_idx, bench in enumerate(benchmarks):
            base = 1000.0 + b_idx * 500.0
            # Inject clear slowdowns on specific benchmarks/commits for triage & FDR testing.
            if bench == "rebar_bench_01" and idx >= 4:
                base *= 1.15
            elif bench == "rebar_bench_02" and idx == 5:
                base *= 1.12
            elif bench == "rebar_bench_03" and idx == 6:
                base *= 1.09
            runs[bench] = [base + (r * 0.5) for r in range(12)]
        hour = 10 + idx + (2 if idx >= 6 else 0)
        commits.append({
            "sha": sha,
            "short_sha": sha[:7],
            "author_date": f"2026-06-{idx + 1:02d}T12:00:00Z",
            "subject": f"feat: commit {idx}",
            "build_ok": True,
            "build_seconds": 1.2,
            "cpu_model": "Test CPU",
            "rustc_version": "rustc 1.99.0",
            "run_started_utc": f"2026-06-01T{hour:02d}:00:00+00:00",
            "run_finished_utc": f"2026-06-01T{hour:02d}:05:00+00:00",
            "runs": runs,
        })
    payload = {"format": 1, "project": project, "commits": commits}
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh)


@pytest.fixture
def scaled_env(tmp_path: Path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    benches = _make_25_benchmarks()
    assert len(benches) == 25

    db_path = tmp_path / "scaled.db"
    commits = [
        {
            "sha": f"{i + 1:07x}" + "a" * 33,
            "short_sha": f"{i + 1:07x}",
            "author_date": f"2026-03-{i + 1:02d}",
            "subject": f"commit {i}",
            "run_started_utc": f"2026-03-01T{10 + i + (3 if i >= 5 else 0):02d}:00:00+00:00",
            "run_finished_utc": f"2026-03-01T{10 + i + (3 if i >= 5 else 0):02d}:05:00+00:00",
            "base_ns": 1000.0 + (200.0 if i >= 4 else 0.0),
        }
        for i in range(8)
    ]
    db, pid, ids = seed_project_db(
        db_path,
        project_name="regex",
        repo_url="https://github.com/rust-lang/regex.git",
        adapter="RegexAdapter",
        commits=commits,
        benchmarks=benches,
        reps=10,
    )

    # Seed 4 flagged comparisons representing all triage statuses.
    flagged_specs = [
        (0, 1, "rebar_bench_01", 12.0, 1e-7, 1.5, 1.0),
        (1, 2, "rebar_bench_02", 4.5, 2e-6, 1.2, 1.0),
        (2, 3, "rebar_bench_03", 3.1, 3e-6, 1.1, 1.0),
        (4, 5, "rebar_bench_04", 8.0, 4e-6, 2.0, 235.0),
    ]
    for b_idx, c_idx, bench, shift, pval, nf, gap in flagged_specs:
        db.insert_comparison(
            project_id=pid,
            base_commit_id=ids[b_idx],
            cand_commit_id=ids[c_idx],
            benchmark=bench,
            p_value=pval,
            shift_pct=shift,
            noise_floor_pct=nf,
            verdict="flag",
            fdr_significant=True,
            session_gap_min=gap,
        )

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    assets_dir = tmp_path / "assets" / "flamegraphs"
    assets_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    fg1 = f"flamegraph_diff_{commits[1]['short_sha']}.svg"
    fg2 = f"flamegraph_diff_{commits[3]['short_sha']}.svg"
    (assets_dir / fg1).write_text("<svg></svg>", encoding="utf-8")
    (assets_dir / fg2).write_text("<svg></svg>", encoding="utf-8")

    (projects_dir / "regex.triage.json").write_text(
        json.dumps([
            {
                "benchmark": "rebar_bench_01",
                "commit": commits[1]["short_sha"],
                "status": "confirmed",
                "note": "Confirmed regression in rebar_bench_01.",
                "issue_url": "https://github.com/rust-lang/regex/issues/4242",
                "flamegraph": fg1,
            },
            {
                "benchmark": "rebar_bench_02",
                "commit": commits[2]["short_sha"],
                "status": "false_positive",
                "note": "Interleaved A/B failed to reproduce.",
            },
            {
                "benchmark": "rebar_bench_03",
                "commit": commits[3]["short_sha"],
                "status": "layout_artifact",
                "note": "LTO binary-layout shift (+0 insns).",
                "flamegraph": fg2,
            },
        ]),
        encoding="utf-8",
    )

    _make_study_fixture(data_dir / "regex_study3_history.json.gz", "regex", benches, n_commits=8)

    app = create_app(
        db_path=str(db_path),
        data_dir=data_dir,
        projects_dir=projects_dir,
        assets_dir=assets_dir,
    )
    return {
        "client": TestClient(app),
        "db_path": db_path,
        "data_dir": data_dir,
        "projects_dir": projects_dir,
        "assets_dir": assets_dir,
        "benches": benches,
        "commits": commits,
        "fg1": fg1,
        "fg2": fg2,
    }


def test_25_benchmark_series_ci_triage_flamegraphs_and_query_budget(scaled_env, monkeypatch):
    client = scaled_env["client"]
    benches = scaled_env["benches"]
    commits = scaled_env["commits"]

    opened = []
    real_connect = sqlite3.connect
    monkeypatch.setattr("core.db.sqlite3.connect", lambda *a, **k: (opened.append(1), real_connect(*a, **k))[1])

    res = client.get("/api/projects/regex/series")
    assert res.status_code == 200
    assert len(opened) <= 8

    payload = res.json()
    assert len(payload["benchmarks"]) == 25
    assert payload["benchmarks"] == sorted(benches)
    assert payload["total_commits"] == 8
    assert len(payload["benchmark_stats"]) == 25

    pt_confirmed = payload["series"]["rebar_bench_01"][1]
    assert pt_confirmed["flagged"] is True
    assert pt_confirmed["triage_status"] == "confirmed"
    assert pt_confirmed["issue_url"] == "https://github.com/rust-lang/regex/issues/4242"
    assert pt_confirmed["flamegraphs"][0]["filename"] == scaled_env["fg1"]
    assert pt_confirmed["ci95_low_ns"] <= pt_confirmed["median_ns"] <= pt_confirmed["ci95_high_ns"]
    assert pt_confirmed["p10_ns"] <= pt_confirmed["median_ns"] <= pt_confirmed["p90_ns"]

    pt_fp = payload["series"]["rebar_bench_02"][2]
    assert pt_fp["flagged"] is True and pt_fp["triage_status"] == "false_positive"

    pt_layout = payload["series"]["rebar_bench_03"][3]
    assert pt_layout["flagged"] is True and pt_layout["triage_status"] == "layout_artifact"

    pt_break = payload["series"]["rebar_bench_04"][5]
    assert pt_break["flagged"] is True
    assert pt_break["triage_status"] == "unreviewed"
    assert pt_break["session_break"] is True
    assert pt_break["session_gap_min"] == 235.0

    # Comparisons overlay triage, issue URLs, and flamegraphs.
    cmps = client.get("/api/projects/regex/comparisons").json()
    by_bench = {c["benchmark"]: c for c in cmps}
    assert by_bench["rebar_bench_01"]["resolution_status"] == "confirmed"
    assert by_bench["rebar_bench_01"]["issue_url"] == "https://github.com/rust-lang/regex/issues/4242"
    assert by_bench["rebar_bench_03"]["resolution_status"] == "layout_artifact"
    assert by_bench["rebar_bench_04"]["session_break"] is True

    # Flamegraphs discovery endpoint
    fgs = client.get("/api/flamegraphs").json()
    assert {f["filename"] for f in fgs} == {scaled_env["fg1"], scaled_env["fg2"]}

    # Distribution drilldown works for all 25 benchmarks on any commit
    dist = client.get(f"/api/commits/{commits[1]['short_sha']}/distribution?project=regex").json()
    assert len(dist["benchmarks"]) == 25


def test_study3_fixture_multi_study_endpoints(scaled_env):
    client = scaled_env["client"]
    studies = client.get("/api/studies").json()
    assert [s["id"] for s in studies] == ["db", "study3"]

    s3_series = client.get("/api/projects/regex/series?study=study3")
    assert s3_series.status_code == 200
    data = s3_series.json()
    assert data["study"] == "study3"
    assert len(data["benchmarks"]) == 25
    assert data["total_commits"] == 8

    s3_cmps = client.get("/api/projects/regex/comparisons?study=study3&fdr=by")
    assert s3_cmps.status_code == 200
    assert len(s3_cmps.json()) == 7 * 25

    s3_sum = client.get("/api/projects/regex/summary?study=study3")
    assert s3_sum.status_code == 200
    sum_body = s3_sum.json()
    assert sum_body["study"] == "study3"
    assert sum_body["benchmarks_count"] == 25
    assert sum_body["comparisons"] == 175
    assert sum_body["regressions_flagged"] >= 1

    dist = client.get("/api/commits/0000005/distribution?project=regex&study=study3")
    assert dist.status_code == 200
    assert len(dist.json()["benchmarks"]) == 25

    cmp_res = client.post(
        "/api/compare",
        json={"project": "regex", "base_sha": "0000001", "cand_sha": "0000005", "study": "study3"},
    )
    assert cmp_res.status_code == 200
    b1_cmp = next(c for c in cmp_res.json()["comparisons"] if c["benchmark"] == "rebar_bench_01")
    assert b1_cmp["verdict"] == "flag"
    assert b1_cmp["shift_pct"] > 10.0

    # Validation checks on invalid study/fdr
    assert client.get("/api/projects/regex/series?study=bad!id").status_code == 400
    assert client.get("/api/projects/regex/series?study=study3&fdr=bonf").status_code == 400


@pytest.mark.skipif(not (STUDY1_DATA.exists() and STUDY2_DATA.exists()), reason="Study 1/2 archives missing")
def test_bundled_study1_and_study2_served_via_api(tmp_path: Path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    db_path = tmp_path / "empty.db"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    studies = {s["id"]: s for s in client.get("/api/studies").json()}
    assert "study1" in studies and "study2" in studies

    s1 = client.get("/api/projects/regex/summary?study=study1").json()
    assert s1["commits_analyzed"] == 27
    assert s1["comparisons"] == 78
    assert s1["regressions_flagged"] == 5
    assert s1["false_positives"] == 5

    s2 = client.get("/api/projects/regex/summary?study=study2").json()
    assert s2["commits_analyzed"] == 24
    assert s2["comparisons"] == 69
    assert s2["regressions_flagged"] == 4
    assert s2["confirmed_real"] == 0
    assert s2["false_positives"] == 4
    assert s2["layout_artifacts"] == 0
    assert s2["unreviewed"] == 0

    fgs = {f["filename"] for f in client.get("/api/flamegraphs").json()}
    assert {"flamegraph_diff.svg", "flamegraph_diff_64ad0b6.svg", "flamegraph_diff_64ad0b6_insn.svg"}.issubset(fgs)

    if STUDY3_DATA.exists():
        assert "study3" in studies
        assert studies["study3"]["projects"] == ["regex"]
        s3 = client.get("/api/projects/regex/summary?study=study3").json()
        assert s3["commits_analyzed"] == 51
        assert s3["benchmarks_count"] == 25
        assert s3["comparisons"] == 1250
        assert s3["regressions_flagged"] == 371
        assert s3["confirmed_real"] == 1
        assert s3["false_positives"] == 328
        assert s3["layout_artifacts"] == 42
        assert s3["unreviewed"] == 0
        s3_series = client.get("/api/projects/regex/series?study=study3").json()
        assert len(s3_series["benchmarks"]) == 25
        assert s3_series["total_commits"] == 51
        redos_pts = s3_series["series"]["rebar_curated_06_cloudflare_redos_long"]
        assert len(redos_pts) == 51
        pt_64 = next(p for p in redos_pts if p["sha"].startswith("64ad0b6"))
        assert pt_64["flagged"] is True
        assert pt_64["triage_status"] == "confirmed"
        pt_fgs = {fg["filename"] for fg in pt_64["flamegraphs"]}
        assert "flamegraph_diff_64ad0b6.svg" in pt_fgs
        assert "flamegraph_diff_64ad0b6_insn.svg" in pt_fgs


def test_ui_dom_safety_and_25_benchmark_features():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    # Strict DOM safety: zero innerHTML/outerHTML/insertAdjacentHTML/document.write anywhere.
    for unsafe_sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert unsafe_sink not in html

    for required_id in (
        "study-selector",
        "project-selector",
        "benchmark-picker",
        "bench-search",
        "bench-status-filter",
        "small-multiples-grid",
        "focus-panel",
        "stat-fp-rate",
        "stat-fp-ci",
        "stat-layout",
        "upstream-issues-bar",
        "flame-tabs",
        "m-bench-select",
    ):
        assert f'id="{required_id}"' in html

    assert "safeExternalUrl" in html
    assert 'rel: "noopener noreferrer"' in html


def test_static_export_generates_self_contained_bundle(scaled_env, tmp_path: Path, monkeypatch, capsys):
    out_dir = tmp_path / "site_out"
    info = export_static_site(
        out_dir,
        db_path=str(scaled_env["db_path"]),
        data_dir=scaled_env["data_dir"],
        projects_dir=scaled_env["projects_dir"],
        assets_dir=scaled_env["assets_dir"],
        ui_dir=ROOT / "ui",
    )
    assert info["studies"] == 2
    assert info["flamegraphs"] == 2
    assert (out_dir / ".nojekyll").is_file()
    assert (out_dir / "static" / "vendor" / "chart.umd.js").is_file()
    assert (out_dir / "flamegraphs" / scaled_env["fg1"]).is_file()

    exported_html = (out_dir / "index.html").read_text(encoding="utf-8")
    assert "window.__REGRESSOR_STATIC__ = true;" in exported_html
    assert 'src="static/vendor/chart.umd.js"' in exported_html
    assert 'href="flamegraphs/' in exported_html
    assert 'href="/flamegraphs/' not in exported_html
    assert 'studiesList.find((s) => s.id !== "db")' in exported_html

    studies = json.loads((out_dir / "api" / "studies.json").read_text(encoding="utf-8"))
    assert [s["id"] for s in studies] == ["db", "study3"]

    s3_series = json.loads((out_dir / "api" / "data" / "study3" / "regex" / "series.json").read_text(encoding="utf-8"))
    assert len(s3_series["benchmarks"]) == 25
    s3_summary = json.loads((out_dir / "api" / "data" / "study3" / "regex" / "summary.json").read_text(encoding="utf-8"))
    assert s3_summary["benchmarks_count"] == 25
    assert (out_dir / "api" / "data" / "study3" / "regex" / "distributions" / "0000001.json").is_file()

    # Empty DB static export omits "db" and still keeps study3 selectable
    empty_out = tmp_path / "empty_site"
    empty_info = export_static_site(
        empty_out,
        db_path=str(tmp_path / "empty.db"),
        data_dir=scaled_env["data_dir"],
        projects_dir=scaled_env["projects_dir"],
        assets_dir=scaled_env["assets_dir"],
        ui_dir=ROOT / "ui",
    )
    assert empty_info["studies"] == 1
    empty_studies = json.loads((empty_out / "api" / "studies.json").read_text(encoding="utf-8"))
    assert [s["id"] for s in empty_studies] == ["study3"]

    # CLI export-site entrypoint works end-to-end
    cli_out = tmp_path / "cli_site"
    monkeypatch.setattr(sys, "argv", ["regressor", "--db", str(scaled_env["db_path"]), "export-site", str(cli_out)])
    assert regressor.main() == 0
    assert (cli_out / "index.html").is_file()
    assert "Exported static site" in capsys.readouterr().out
