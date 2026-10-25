"""
Tests for the review fixes: p-value floor reporting, Benjamini-Yekutieli, bisect confirmation
without optional stopping, unique SHA-prefix resolution, CLI argument validation, and the
in-place RegexAdapter source guard.
"""

from pathlib import Path
from typing import Dict, List, Optional

import pytest

from adapters.base import BaseAdapter
from core.bisect import bisect_builds
from core.db import resolve_commit_prefix
from core.detector import bh_fdr_correct
from core.interleaved import analyze_paired, min_wilcoxon_p
from core.models import BuildResult
from core.report import render_markdown

# ---------------------------------------------------------------------------
# p-value floor
# ---------------------------------------------------------------------------


def test_all_same_sign_pairs_are_reported_at_the_floor():
    a = [1000.0 + i for i in range(30)]
    b = [x * (1.04 + i * 0.001) for i, x in enumerate(a)]  # every pair slower, all diffs distinct
    r = analyze_paired(a, b)
    assert r["nonzero_pairs"] == 30
    assert r["min_achievable_p"] == pytest.approx(min_wilcoxon_p(30))
    assert r["p_value"] == pytest.approx(1.862645149230957e-09)
    assert r["p_at_floor"] is True


def test_mixed_sign_pairs_are_not_at_the_floor():
    a = [1000.0] * 12
    b = [1000.0 + (5 if i % 3 else -4) + i * 0.1 for i in range(12)]
    r = analyze_paired(a, b)
    assert r["p_at_floor"] is False


def test_floor_uses_nonzero_pairs_only():
    a = [1000.0] * 12
    b = [1000.0] * 4 + [1010.0 + i for i in range(8)]       # 4 zero diffs are dropped by the test
    r = analyze_paired(a, b)
    assert r["nonzero_pairs"] == 8
    assert r["min_achievable_p"] == pytest.approx(min_wilcoxon_p(8))


def _result(**over):
    base = {"benchmark": "b1", "pairs": 30, "baseline_median_ns": 1000.0, "candidate_median_ns": 1041.0,
            "shift_pct": 4.1, "shift_ci95_pct": [3.68, 4.51], "p_value": 1.86e-9, "alpha": 0.01,
            "min_effect_pct": 1.0, "final_verdict": "flag", "p_at_floor": True, "require_ci_bound": False}
    base.update(over)
    return base


def test_report_marks_floor_and_explains_it():
    md = render_markdown("aaaa", "bbbb", [_result()], env={})
    assert "(floor)" in md
    assert "every pair moved in the same direction" in md


def test_report_flag_rule_reflects_require_ci_bound():
    loose = render_markdown("aaaa", "bbbb", [_result(require_ci_bound=False)], env={})
    strict = render_markdown("aaaa", "bbbb", [_result(require_ci_bound=True)], env={})
    assert "|shift| > 1.0%" in loose
    assert "95% CI bound clears 1.0%" in strict


# ---------------------------------------------------------------------------
# Benjamini-Yekutieli
# ---------------------------------------------------------------------------


def test_by_is_more_conservative_than_bh():
    ps = [0.001, 0.008, 0.012, 0.02, 0.03, 0.2, 0.5, 0.9]
    bh = bh_fdr_correct([{"p_value": p} for p in ps], alpha=0.05, method="bh")
    by = bh_fdr_correct([{"p_value": p} for p in ps], alpha=0.05, method="by")
    n_bh = sum(c["fdr_significant"] for c in bh)
    n_by = sum(c["fdr_significant"] for c in by)
    assert n_bh == 5
    assert n_by == 1        # alpha / H(8) = 0.05 / 2.718 -> only p=0.001 survives
    assert all(c_bh["fdr_significant"] for c_bh, c_by in zip(bh, by) if c_by["fdr_significant"])


def test_fdr_rejects_unknown_method():
    with pytest.raises(ValueError):
        bh_fdr_correct([{"p_value": 0.01}], method="bonferroni")


def test_default_fdr_is_bh_and_keeps_the_original_study(tmp_path: Path, monkeypatch):
    import regressor
    db = tmp_path / "s.db"
    monkeypatch.setattr("sys.argv", ["regressor.py", "--db", str(db), "import-data", "data/regex_history.json.gz"])
    assert regressor.main() == 0
    monkeypatch.setattr("sys.argv", ["regressor.py", "--db", str(db), "batch", "regex", "--verify-legacy"])
    assert regressor.main() == 0
    monkeypatch.setattr("sys.argv", ["regressor.py", "--db", str(db), "batch", "regex", "--fdr", "by"])
    assert regressor.main() == 0
    # --verify-legacy is a BH reproduction; combining it with BY is refused, not silently "passed"
    monkeypatch.setattr("sys.argv", ["regressor.py", "--db", str(db), "batch", "regex", "--fdr", "by", "--verify-legacy"])
    assert regressor.main() == 1


# ---------------------------------------------------------------------------
# Bisect: borderline probes are decided by an independent confirmation batch
# ---------------------------------------------------------------------------


class _ScriptedAdapter(BaseAdapter):
    """Good build is always 1000 ns. Each candidate returns values from a per-ref script, one
    entry per run() call on that candidate (pairs run A and B, so B calls == pairs)."""

    def __init__(self, commits: List[str], script: Dict[str, List[float]], default_bad_from: int):
        self.commits = commits
        self.script = script
        self.calls: Dict[str, int] = {}
        self.default_bad_from = default_bad_from

    def list_benchmarks(self) -> List[str]:
        return ["b1"]

    def build(self, commit_ref: str, workdir: Optional[Path] = None) -> BuildResult:
        return BuildResult(ok=True, seconds=0.0, log_tail="", artifact=commit_ref)

    def run(self, bench_name, iters, warmup, inject_ns=0, artifact=None) -> List[float]:
        if artifact == self.commits[0]:
            return [1000.0] * 5
        k = self.calls.get(artifact, 0)
        self.calls[artifact] = k + 1
        if artifact in self.script:
            seq = self.script[artifact]
            return [seq[min(k, len(seq) - 1)]] * 5
        return [1080.0 if self.commits.index(artifact) >= self.default_bad_from else 1000.0] * 5


def test_borderline_probe_uses_only_the_confirmation_batch():
    commits = [f"c{i:02d}" for i in range(8)]
    # c03 (truly bad here) looks borderline in batch 1 and clearly bad in batch 2.
    # Batch 1: alternating +0.4% / +2.2% -> borderline flag (CI does not clear 1%).
    first = [1004.0 if (i % 2) else 1022.0 for i in range(12)]
    second = [1080.0] * 12
    adapter = _ScriptedAdapter(commits, {"c03": first + second}, default_bad_from=3)
    res = bisect_builds(adapter, commits, "b1", pairs=12, log=lambda _: None)
    step = next(s for s in res["steps"] if s["ref"] == "c03")
    assert step["repeated"] is True
    assert step["shift_pct"] == pytest.approx(8.0, abs=0.01)   # the decision batch, not a pooled mix
    assert res["culprit"] == "c03"


def test_confirmation_batch_can_overturn_a_borderline_flag():
    commits = [f"c{i:02d}" for i in range(8)]
    first = [1004.0 if (i % 2) else 1022.0 for i in range(12)]
    second = [1000.0] * 12                                     # spike gone on re-measurement
    adapter = _ScriptedAdapter(commits, {"c03": first + second}, default_bad_from=5)
    res = bisect_builds(adapter, commits, "b1", pairs=12, log=lambda _: None)
    assert res["culprit"] == "c05"
    assert res["last_good"] == "c04"


# ---------------------------------------------------------------------------
# SHA prefix resolution
# ---------------------------------------------------------------------------

_COMMITS = [
    {"id": 1, "sha": "abcd1111ffff", "short_sha": "abcd111"},
    {"id": 2, "sha": "abcd2222ffff", "short_sha": "abcd222"},
    {"id": 3, "sha": "9999aaaa0000", "short_sha": "9999aaa"},
]


def test_unique_prefix_resolves():
    c, err = resolve_commit_prefix(_COMMITS, "9999")
    assert err is None and c["id"] == 3


@pytest.mark.parametrize("prefix,needle", [("abcd", "ambiguous"), ("abc", "too short"), ("", "too short"),
                                           ("ffff0000", "not found")])
def test_bad_prefixes_are_errors(prefix, needle):
    c, err = resolve_commit_prefix(_COMMITS, prefix)
    assert c is None and needle in err


def test_api_compare_rejects_ambiguous_prefix(tmp_path: Path):
    from fastapi.testclient import TestClient

    from core.db import Database
    from server.app import create_app

    db_path = tmp_path / "amb.db"
    db = Database(str(db_path))
    pid = db.register_project("regex", "", "", "RegexAdapter", "")
    for sha in ("abcd1111ffff", "abcd2222ffff", "9999aaaa0000"):
        cid = db.insert_commit(pid, sha, sha[:7], "", "s", True, 0.0)
        db.insert_runs_bulk((cid, "b1", i, "", 1000.0 + i) for i in range(1, 6))
    client = TestClient(create_app(str(db_path)))
    r = client.post("/api/compare", json={"project": "regex", "base_sha": "abcd", "cand_sha": "9999"})
    assert r.status_code == 400
    assert "ambiguous" in r.json()["detail"]
    r = client.post("/api/compare", json={"project": "regex", "base_sha": "abcd1", "cand_sha": "9999"})
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# CLI argument validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("argv", [
    ["compare-interleaved", "--base", "a", "--cand", "b", "--alpha", "2"],
    ["compare-interleaved", "--base", "a", "--cand", "b", "--alpha", "0"],
    ["compare-interleaved", "--base", "a", "--cand", "b", "--warmup", "-1"],
    ["compare-interleaved", "--base", "a", "--cand", "b", "--inject-ns", "-5"],
    ["compare-interleaved", "--base", "a", "--cand", "b", "--canary-reps", "-1"],
    ["compare-interleaved", "--base", "a", "--cand", "b", "--min-effect", "-1"],
    ["evaluate-power", "--trials", "0"],
    ["changepoint", "--alpha", "1.5"],
    ["batch", "--fdr", "bonferroni"],
])
def test_cli_rejects_out_of_range_arguments(argv, monkeypatch):
    import regressor
    monkeypatch.setattr("sys.argv", ["regressor.py", *argv])
    with pytest.raises(SystemExit) as exc:
        regressor.main()
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# RegexAdapter in-place mode
# ---------------------------------------------------------------------------


def test_in_place_build_refuses_a_clone_it_would_not_compile(tmp_path: Path, monkeypatch):
    import shutil

    from adapters.regex_adapter import RegexAdapter

    other = tmp_path / "elsewhere"
    (other / ".git").mkdir(parents=True)
    monkeypatch.setattr(shutil, "which", lambda tool: f"/usr/bin/{tool}")
    res = RegexAdapter(regex_repo_dir=str(other)).build("HEAD", workdir=None)
    assert res.ok is False
    assert "in-place build needs the clone" in res.log_tail
