"""
tests/test_published_numbers.py
Pin every published headline metric for Studies 1, 2, and 3 directly from
`data/*.json.gz` through the `regressor.py summary` code path (both `--study`
archive loading and temp-SQLite `init` + `import-data` + `batch` + `summary`),
and verify `README.md` and `noise-bench/REPORT.md` match those computed numbers.
"""

from __future__ import annotations

import contextlib
import gzip
import io
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

import regressor

ROOT = Path(__file__).resolve().parent.parent

STUDY_SPECS: Tuple[Tuple[str, str, str], ...] = (
    ("study1", "regex_history.json.gz", "bh"),
    ("study2", "regex_study2_history.json.gz", "by"),
    ("study3", "regex_study3_history.json.gz", "by"),
)

SUMMARY_KEYS: Tuple[str, ...] = (
    "commits_analyzed",
    "benchmarks_count",
    "comparisons",
    "flagged_pre_fdr",
    "regressions_flagged",
    "confirmed_real",
    "false_positives",
    "layout_artifacts",
    "unreviewed",
    "fp_rate_pct",
    "fp_rate_wilson_ci95_pct",
)


def _run_regressor(argv: List[str]) -> str:
    """Invoke `regressor.main()` with temporary `sys.argv` and return stdout."""
    old_argv = sys.argv
    buf = io.StringIO()
    try:
        sys.argv = argv
        with contextlib.redirect_stdout(buf):
            rc = regressor.main()
    finally:
        sys.argv = old_argv
    assert rc == 0, f"regressor command failed (rc={rc}): {' '.join(argv)}"
    return buf.getvalue()


def _count_archive_runs(gz_path: Path) -> int:
    """Count total recorded per-run medians inside a `.json.gz` study archive."""
    with gzip.open(gz_path, "rt", encoding="utf-8") as fh:
        payload = json.load(fh)
    return sum(
        len(medians)
        for commit in payload.get("commits") or []
        for medians in (commit.get("runs") or {}).values()
    )


def _parse_markdown_table(text: str, header_prefix: str) -> Dict[str, List[str]]:
    """Extract pipe-delimited rows into `{first_col: remaining_cols}`."""
    rows: Dict[str, List[str]] = {}
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if not line.startswith(header_prefix):
            continue
        for row_line in lines[idx + 2 :]:
            if not row_line.startswith("|"):
                break
            cells = [c.strip() for c in row_line.strip().strip("|").split("|")]
            if cells:
                rows[cells[0]] = cells[1:]
        break
    return rows


@pytest.fixture(scope="module")
def published_summaries(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, Dict[str, Any]]:
    """Compute Study 1, 2, and 3 summaries via `--study` and temp-DB paths."""
    tmp_dir = tmp_path_factory.mktemp("published_numbers")
    out: Dict[str, Dict[str, Any]] = {}

    for sid, filename, fdr in STUDY_SPECS:
        gz_path = ROOT / "data" / filename
        assert gz_path.is_file(), f"Missing study dataset: {gz_path}"

        archive_db = str(tmp_dir / f"{sid}_archive.db")
        archive_json = _run_regressor(
            ["regressor.py", "--db", archive_db, "summary", "regex", "--study", sid, "--json"]
        )
        archive_summary = json.loads(archive_json)

        temp_db = str(tmp_dir / f"{sid}_db.db")
        for sub_cmd in (
            ["init"],
            ["import-data", str(gz_path)],
            ["batch", "regex", "--fdr", fdr],
        ):
            _run_regressor(["regressor.py", "--db", temp_db, *sub_cmd])
        db_json = _run_regressor(["regressor.py", "--db", temp_db, "summary", "regex", "--json"])
        db_summary = json.loads(db_json)

        out[sid] = {
            "archive": archive_summary,
            "db": db_summary,
            "total_runs": _count_archive_runs(gz_path),
        }

    return out


def test_archive_and_temp_db_summary_paths_agree(published_summaries: Dict[str, Dict[str, Any]]) -> None:
    for sid, _, _ in STUDY_SPECS:
        archive_s = published_summaries[sid]["archive"]
        db_s = published_summaries[sid]["db"]
        for key in SUMMARY_KEYS:
            assert archive_s[key] == db_s[key], f"{sid} mismatch on {key}: {archive_s[key]} vs {db_s[key]}"


def test_study1_published_numbers(published_summaries: Dict[str, Dict[str, Any]]) -> None:
    entry = published_summaries["study1"]
    s = entry["db"]
    assert entry["total_runs"] == 1620
    assert s["commits_analyzed"] == 27
    assert s["benchmarks_count"] == 3
    assert s["comparisons"] == 78
    assert s["flagged_pre_fdr"] == 5
    assert s["regressions_flagged"] == 5
    assert s["confirmed_real"] == 0
    assert s["false_positives"] == 5
    assert s["layout_artifacts"] == 0
    assert s["unreviewed"] == 0
    assert s["fp_rate_pct"] == pytest.approx(100.0, abs=1e-9)
    assert s["fp_rate_wilson_ci95_pct"] == [56.55, 100.0]


def test_study2_published_numbers(published_summaries: Dict[str, Dict[str, Any]]) -> None:
    entry = published_summaries["study2"]
    s = entry["db"]
    assert entry["total_runs"] == 1440
    assert s["commits_analyzed"] == 24
    assert s["benchmarks_count"] == 3
    assert s["comparisons"] == 69
    assert s["flagged_pre_fdr"] == 4
    assert s["regressions_flagged"] == 4
    assert s["confirmed_real"] == 0
    assert s["false_positives"] == 4
    assert s["layout_artifacts"] == 0
    assert s["unreviewed"] == 0
    assert s["fp_rate_pct"] == pytest.approx(100.0, abs=1e-9)
    assert s["fp_rate_wilson_ci95_pct"] == [51.01, 100.0]


def test_study3_published_numbers_and_wilson_ci(published_summaries: Dict[str, Dict[str, Any]]) -> None:
    entry = published_summaries["study3"]
    s = entry["db"]
    assert entry["total_runs"] == 19125
    assert s["commits_analyzed"] == 51
    assert s["benchmarks_count"] == 25
    assert s["comparisons"] == 1250
    assert s["flagged_pre_fdr"] == 371
    assert s["regressions_flagged"] == 371
    assert s["confirmed_real"] == 1
    assert s["false_positives"] == 328
    assert s["layout_artifacts"] == 42
    assert s["unreviewed"] == 0
    assert round(s["fp_rate_pct"], 1) == 88.4
    assert s["fp_rate_pct"] == pytest.approx(88.41, abs=1e-9)

    lo, hi = s["fp_rate_wilson_ci95_pct"]
    assert f"[{lo:.2f}%, {hi:.2f}%]" == "[84.75%, 91.28%]"
    assert [lo, hi] == [84.75, 91.28]

    confirmed_items = [item for item in s["flagged_items"] if item["status"] == "confirmed"]
    assert len(confirmed_items) == 1
    assert confirmed_items[0]["cand_sha"].startswith("64ad0b6")
    assert confirmed_items[0]["benchmark"] == "rebar_curated_06_cloudflare_redos_long"
    assert confirmed_items[0]["shift_pct"] == pytest.approx(94.38, abs=0.02)


def test_readme_headline_numbers_match_computed_summaries(
    published_summaries: Dict[str, Dict[str, Any]],
) -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    lines = readme.splitlines()

    s1 = published_summaries["study1"]["db"]
    s2 = published_summaries["study2"]["db"]
    s3 = published_summaries["study3"]["db"]
    total_runs_s3 = published_summaries["study3"]["total_runs"]
    ci3 = s3["fp_rate_wilson_ci95_pct"]

    row_s1 = next(ln for ln in lines if ln.startswith("| **Study 1"))
    row_s2 = next(ln for ln in lines if ln.startswith("| **Study 2"))
    row_s3 = next(ln for ln in lines if ln.startswith("| **Study 3"))

    assert f"{s1['commits_analyzed']} source-touching commits" in row_s1
    assert f"| {s1['comparisons']} (" in row_s1
    assert f"| {s1['regressions_flagged']} ({s1['false_positives']}/{s1['regressions_flagged']} false positives)" in row_s1
    assert f"| **{s1['confirmed_real']}** |" in row_s1

    assert f"{s2['commits_analyzed']} commits" in row_s2
    assert f"| {s2['comparisons']} (" in row_s2
    assert f"| {s2['regressions_flagged']} (" in row_s2
    assert f"| **{s2['confirmed_real']}** |" in row_s2

    assert f"**{s3['commits_analyzed']}** commits" in row_s3
    assert f"{s3['benchmarks_count']} Benches" in row_s3
    assert f"| {s3['comparisons']:,} (" in row_s3
    assert f"| {s3['regressions_flagged']} (" in row_s3
    assert f"`{s3['false_positives']}` FP = **{s3['fp_rate_pct']:.1f}%**" in row_s3
    assert f"[{ci3[0]:.2f}%, {ci3[1]:.2f}%]" in row_s3
    assert f"`{s3['layout_artifacts']}` LTO layout artifacts" in row_s3
    assert f"| **{s3['confirmed_real']}** (`64ad0b6`" in row_s3
    assert f"`{s3['unreviewed']}` unreviewed" in row_s3

    for expected in (
        f"**{s3['commits_analyzed']}** commits",
        f"**{s3['comparisons']:,}** comparisons",
        f"**{s3['regressions_flagged']}** BY-FDR flags",
        f"**{s3['false_positives']}** false positives",
        f"**{s3['fp_rate_pct']:.1f}%**",
        f"[{ci3[0]:.2f}%, {ci3[1]:.2f}%]",
        f"**{s3['layout_artifacts']}** LTO layout artifacts",
        f"**{s3['unreviewed']}** unreviewed",
        f"`{total_runs_s3:,}` runs",
        "64ad0b6",
        "rebar_curated_06_cloudflare_redos_long",
    ):
        assert expected in readme, f"README.md missing headline token: {expected!r}"


def test_report_md_headline_numbers_match_computed_summaries(
    published_summaries: Dict[str, Dict[str, Any]],
) -> None:
    report = (ROOT / "noise-bench" / "REPORT.md").read_text(encoding="utf-8")
    table = _parse_markdown_table(report, "| Metric | Study 1")
    assert len(table) >= 8

    s1 = published_summaries["study1"]["db"]
    s2 = published_summaries["study2"]["db"]
    s3 = published_summaries["study3"]["db"]
    ci1 = s1["fp_rate_wilson_ci95_pct"]
    ci2 = s2["fp_rate_wilson_ci95_pct"]
    ci3 = s3["fp_rate_wilson_ci95_pct"]
    total_runs_s3 = published_summaries["study3"]["total_runs"]

    assert table["Commits analyzed"][0].startswith(str(s1["commits_analyzed"]))
    assert table["Commits analyzed"][1].startswith(str(s2["commits_analyzed"]))
    assert table["Commits analyzed"][2].startswith(str(s3["commits_analyzed"]))

    assert table["Benchmarks"][0].startswith(str(s1["benchmarks_count"]))
    assert table["Benchmarks"][1].startswith(str(s2["benchmarks_count"]))
    assert table["Benchmarks"][2].startswith(str(s3["benchmarks_count"]))

    assert table["Pairwise comparisons"][0].startswith(str(s1["comparisons"]))
    assert table["Pairwise comparisons"][1].startswith(str(s2["comparisons"]))
    assert table["Pairwise comparisons"][2].startswith(f"{s3['comparisons']:,}")

    assert table["Flagged, pre-FDR / BH / BY"] == [
        f"{s1['flagged_pre_fdr']} / {s1['regressions_flagged']} / {s1['regressions_flagged']}",
        f"{s2['flagged_pre_fdr']} / {s2['regressions_flagged']} / {s2['regressions_flagged']}",
        f"{s3['flagged_pre_fdr']} / {s3['regressions_flagged']} / {s3['regressions_flagged']}",
    ]

    assert table["Confirmed real regressions"][0] == f"**{s1['confirmed_real']}**"
    assert table["Confirmed real regressions"][1] == f"**{s2['confirmed_real']}**"
    assert table["Confirmed real regressions"][2].startswith(f"**{s3['confirmed_real']}**")
    assert "64ad0b6" in table["Confirmed real regressions"][2]

    fp_row = table["False positives (FP rate)"]
    assert f"{s1['false_positives']}/{s1['regressions_flagged']}" in fp_row[0]
    assert f"[{ci1[0]:.2f}%, {ci1[1]:.2f}%]" in fp_row[0]
    assert f"{s2['false_positives']}/{s2['regressions_flagged']}" in fp_row[1]
    assert f"[{ci2[0]:.2f}%, {ci2[1]:.2f}%]" in fp_row[1]
    assert f"{s3['false_positives']}/{s3['regressions_flagged']} = {s3['fp_rate_pct']:.1f}%" in fp_row[2]
    assert f"[{ci3[0]:.2f}%, {ci3[1]:.2f}%]" in fp_row[2]

    assert table["LTO layout artifacts"][0].startswith(str(s1["layout_artifacts"]))
    assert table["LTO layout artifacts"][1].startswith(str(s2["layout_artifacts"]))
    assert table["LTO layout artifacts"][2].startswith(str(s3["layout_artifacts"]))

    assert table["Unreviewed flags"] == [
        str(s1["unreviewed"]),
        str(s2["unreviewed"]),
        str(s3["unreviewed"]),
    ]

    assert f"`{total_runs_s3:,}` runs" in report
    assert "rebar_curated_06_cloudflare_redos_long" in report
