"""Stage 4 tests: security hardening, autocorrelation/block-bootstrap, CI-bound gate,
borderline bisect re-probing, rolling-window outlier filtering, SVG escaping, and UI audit.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pytest

import regressor
from adapters.base import BaseAdapter, BuildResult
from adapters.regex_adapter import RegexAdapter
from core.bisect import bisect_builds, git_rev_list, validate_git_ref
from core.db import Database
from core.detector import (
    block_bootstrap_p_value,
    compare_distributions,
    effective_sample_size,
    lag1_autocorr,
)
from core.interleaved import analyze_paired, run_interleaved
from core.samples import parse_samples
from core.series_detector import rolling_baseline_compare


def load_flamegraph_module():
    spec = importlib.util.spec_from_file_location(
        "flamegraph", Path("noise-bench/analyze/flamegraph.py")
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 1. Security & Input Validation Tests
# ---------------------------------------------------------------------------


def test_project_name_rejects_path_traversal():
    for bad_name in ["../etc/passwd", "..\\secret", "foo/bar", "foo\\bar", "", "-flag", "a..b"]:
        with pytest.raises(ValueError, match="Invalid project name"):
            regressor.load_project_config(bad_name)
        with pytest.raises(ValueError, match="Invalid project name"):
            regressor._load_triage(bad_name)


def test_git_ref_validation_blocks_option_injection(tmp_path: Path):
    for bad_ref in [
        "--upload-pack=evil",
        "-f",
        "--help",
        "HEAD..origin",
        "abc@{0}",
        "ref with spaces",
        "ref\x00null",
        "",
    ]:
        with pytest.raises(ValueError, match="Invalid or unsafe git ref"):
            validate_git_ref(bad_ref)

    for good_ref in ["16d47c5", "0a446ec", "HEAD", "v1.10.0", "feature/fast_dfa", "main~1", "main^2"]:
        assert validate_git_ref(good_ref) == good_ref

    adapter = RegexAdapter(noise_bench_dir=str(tmp_path), regex_repo_dir=str(tmp_path))
    br = adapter.build("--upload-pack=touch_pwned")
    assert br.ok is False
    assert "Invalid or unsafe git ref" in br.log_tail


def test_git_rev_list_on_real_repo(tmp_path: Path):
    import shutil
    import subprocess

    if not shutil.which("git"):
        pytest.skip("git not installed on PATH")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    shas = []
    for i in range(3):
        (repo / "f.txt").write_text(f"v{i}\n", encoding="utf-8")
        subprocess.run(["git", "add", "f.txt"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"c{i}"], cwd=repo, check=True, capture_output=True)
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
        ).stdout.strip()
        shas.append(sha)

    res = git_rev_list(repo, shas[0][:7], shas[2][:7])
    assert res == shas
    with pytest.raises(ValueError, match="Invalid or unsafe git ref"):
        git_rev_list(repo, "--bad-flag", shas[2][:7])


def test_samples_rejects_non_positive_values():
    with pytest.raises(ValueError, match="non-positive sample"):
        parse_samples("0\n100\n200\n", expected=3)

    with pytest.raises(ValueError, match="non-positive sample"):
        parse_samples("-5\n100\n200\n", expected=3)


def test_interleaved_rejects_non_positive_or_non_finite_pairs():
    with pytest.raises(ValueError, match="strictly positive"):
        analyze_paired([0.0, 100.0, 100.0, 100.0, 100.0], [100.0] * 5)

    with pytest.raises(ValueError, match="finite"):
        analyze_paired([float("nan"), 100.0, 100.0, 100.0, 100.0], [100.0] * 5)


def test_database_reinitializes_when_recreated_as_zero_byte_file(tmp_path: Path):
    db_file = tmp_path / "ephemeral.db"
    db1 = Database(str(db_file))
    db1.register_project("p1", "https://example.com/p1.git", "", "PyMicroAdapter", "")
    assert db1.get_project_id("p1") is not None

    # Simulate file deletion and empty touch at the same path inside the same process
    db_file.unlink()
    db_file.write_bytes(b"")
    assert db_file.stat().st_size == 0

    db2 = Database(str(db_file))
    assert db2.get_project_id("p1") is None
    db2.register_project("p2", "https://example.com/p2.git", "", "PyMicroAdapter", "")
    assert db2.get_project_id("p2") is not None


def test_flamegraph_svg_escapes_rust_generics_and_xss():
    fg = load_flamegraph_module()
    base = {
        "main;<core::fmt::Write as std::io::Write>::write_fmt": 100,
        'main;fn_with_"quotes"_and_<script>alert(1)</script>': 80,
    }
    cand = {
        "main;<core::fmt::Write as std::io::Write>::write_fmt": 140,
        'main;fn_with_"quotes"_and_<script>alert(1)</script>': 90,
    }
    svg, count = fg.generate_diff_svg(base, 180, cand, 230, title='Title <unsafe> & "quoted"')
    assert count >= 2
    assert "<script>alert(1)</script>" not in svg
    assert "<core::fmt::Write" not in svg
    assert "&lt;core::fmt::Write" in svg
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in svg
    assert "clip-path=" not in svg


# ---------------------------------------------------------------------------
# 2. Autocorrelation & Block Bootstrap Tests (Handoff #4)
# ---------------------------------------------------------------------------


def test_lag1_autocorr_and_effective_sample_size():
    rng = np.random.default_rng(42)
    # Generate strongly positively autocorrelated AR(1) series: x_t = 0.8 * x_{t-1} + e_t
    n = 60
    ar = np.zeros(n)
    ar[0] = 1000.0
    for i in range(1, n):
        ar[i] = 1000.0 + 0.8 * (ar[i - 1] - 1000.0) + rng.normal(0.0, 5.0)

    r1 = lag1_autocorr(ar.tolist())
    assert r1 > 0.5
    n_eff = effective_sample_size(ar.tolist())
    assert n_eff < n * 0.4

    # Block bootstrap p-value between two segments of the same autocorrelated process
    # is much more conservative than naive i.i.d. Mann-Whitney when a random walk drifts.
    base = [1000.0 + i * 0.6 for i in range(20)]
    cand = [1006.0 + i * 0.6 for i in range(20)]
    res_default = compare_distributions(base, cand, adjust_autocorr=False)
    res_adjusted = compare_distributions(base, cand, adjust_autocorr=True)

    assert "baseline_lag1_r" in res_default
    assert "effective_n_baseline" in res_default
    assert "block_bootstrap_p_value" in res_default
    assert res_default["baseline_lag1_r"] > 0.8
    assert res_default["effective_n_baseline"] < 5.0
    assert res_adjusted["block_bootstrap_p_value"] >= res_default["p_value"]


def test_block_bootstrap_detects_genuine_shift():
    rng = np.random.default_rng(7)
    base = (1000.0 + rng.normal(0.0, 2.0, size=20)).tolist()
    cand = (1050.0 + rng.normal(0.0, 2.0, size=20)).tolist()
    p_bb = block_bootstrap_p_value(base, cand, n_boot=500, seed=7)
    assert p_bb < 0.01
    res = compare_distributions(base, cand, adjust_autocorr=True)
    assert res["verdict"] == "flag"


# ---------------------------------------------------------------------------
# 3. Interleaved CI-Bound Gate Tests (Handoff #5)
# ---------------------------------------------------------------------------


def test_interleaved_require_ci_bound_gates_borderline_shift():
    # Construct paired samples where the median shift is ~2.2% (> 2.0% min_effect),
    # p-value < 0.01, but the 95% CI lower bound is < 2.0% (so CI does not clear 2.0%).
    base = [1000.0] * 20
    cand = [1008.0 if (i % 2 == 0) else 1036.0 for i in range(20)]

    res_point = analyze_paired(base, cand, min_effect_pct=2.0, require_ci_bound=False)
    res_ci = analyze_paired(base, cand, min_effect_pct=2.0, require_ci_bound=True)

    assert abs(res_point["shift_pct"]) > 2.0
    assert res_point["shift_ci95_pct"][0] < 2.0
    assert res_point["ci_clears_min_effect"] is False
    assert res_point["verdict"] == "flag"
    assert res_ci["verdict"] == "ok"

    # When shift is well above min_effect (e.g. +8%), both modes flag it
    rng = np.random.default_rng(123)
    cand_strong = [b * 1.08 + float(rng.normal(0, 1.0)) for b in base]
    res_strong = analyze_paired(base, cand_strong, min_effect_pct=2.0, require_ci_bound=True)
    assert res_strong["ci_clears_min_effect"] is True
    assert res_strong["verdict"] == "flag"


def test_run_interleaved_forwards_require_ci_bound():
    class BorderlineAdapter(BaseAdapter):
        def __init__(self):
            self._b_call = 0

        def list_benchmarks(self) -> List[str]:
            return ["bench1"]

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
            if artifact == "base":
                return [1000.0] * 10
            self._b_call += 1
            # Alternating 0.8% and 3.6% shifts so HL is ~2.2% while lower CI bound is < 2.0%
            val = 1008.0 if (self._b_call % 2 == 0) else 1036.0
            return [val] * 10

    r_loose = run_interleaved(
        BorderlineAdapter(),
        "bench1",
        "base",
        "cand",
        pairs=16,
        min_effect_pct=2.0,
        require_ci_bound=False,
        seed=99,
    )
    r_strict = run_interleaved(
        BorderlineAdapter(),
        "bench1",
        "base",
        "cand",
        pairs=16,
        min_effect_pct=2.0,
        require_ci_bound=True,
        seed=99,
    )
    assert r_loose["verdict"] == "flag"
    assert r_strict["verdict"] == "ok"


# ---------------------------------------------------------------------------
# 4. Bisect Borderline Re-Probing Tests (Handoff #6)
# ---------------------------------------------------------------------------


def test_bisect_repeats_borderline_probe_and_recovers_culprit():
    commits = [f"c{i:02d}" for i in range(8)]
    culprit_idx = 5  # c05 is the first bad commit
    cand_pair_calls: Dict[str, int] = {}

    class FlakyMidpointAdapter(BaseAdapter):
        def list_benchmarks(self) -> List[str]:
            return ["b1"]

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
            assert artifact is not None
            idx = commits.index(artifact)
            if artifact == "c03":
                # First 12 pairs on c03 (actually good) experience a borderline false-flag spike
                # (alternating +0.4% and +2.2% -> HL ~1.3%, CI lower bound < 1.0%, so ci_clears_min_effect=False).
                # When bisect repeats c03 for pairs 13..24, the spike is gone (1000.0 ns),
                # so the pooled 24-pair test rejects the false flag!
                cand_pair_calls["c03"] = cand_pair_calls.get("c03", 0) + 1
                k = cand_pair_calls["c03"]
                if k <= 12:
                    return [1004.0 if (k % 2 == 0) else 1022.0] * 10
                return [1000.0] * 10
            if idx < culprit_idx:
                return [1000.0] * 10
            return [1080.0] * 10

    res = bisect_builds(
        FlakyMidpointAdapter(),
        commits,
        "b1",
        pairs=12,
        min_effect_pct=1.0,
        repeat_borderline=True,
        log=lambda _: None,
    )
    assert cand_pair_calls.get("c03") == 24  # 12 initial pairs + 12 repeat pairs
    assert res["culprit"] == "c05"
    assert res["last_good"] == "c04"
    assert res["reproduced"] is True


# ---------------------------------------------------------------------------
# 5. Rolling Baseline Persistent-Step Stability Test (Handoff #7)
# ---------------------------------------------------------------------------


def test_rolling_baseline_does_not_reflag_persistent_step_at_b():
    rng = np.random.default_rng(101)
    # History [A, A, B] where B is a +10% step (~1100ns) that already occurred at the
    # previous commit, and the new candidate commit is also at level B (~1100ns).
    # Rolling baseline must stay quiet ('ok') rather than discarding B and re-flagging +10%.
    history = [
        (1000.0 + rng.normal(0, 3.0, size=20)).tolist(),
        (1000.0 + rng.normal(0, 3.0, size=20)).tolist(),
        (1100.0 + rng.normal(0, 3.0, size=20)).tolist(),
    ]
    cand = (1100.0 + rng.normal(0, 3.0, size=20)).tolist()
    res = rolling_baseline_compare(history, cand, window_k=3)
    assert res["window_size_commits"] == 3
    assert res["stable_commits_used"] == 3
    assert res["rolling_baseline_n"] == 60
    assert res["verdict"] == "ok"


# ---------------------------------------------------------------------------
# 6. UI & Rust Harness Source Verification Tests (Handoff #2, #3, #8)
# ---------------------------------------------------------------------------


def test_ui_respects_design_rules_and_escapes_dom():
    html = Path("ui/index.html").read_text(encoding="utf-8")
    # No italic serif subtitle or <i>and</i> in footer
    assert "font-style: italic" not in html
    assert "<i>and</i>" not in html
    # No coloured 3px left border on .session-banner
    assert "border-left: 3px solid" not in html
    # No stale hardcoded go_json option in initial HTML
    assert 'value="go_json"' not in html
    # Escaping helper present and inline onclick with cand_sha removed
    assert "function esc(" in html
    assert "openDrillModal('${c.cand_sha}')" not in html
    # Drill-down modal passes project query param and has benchmark selector
    assert "distribution?project=" in html
    assert 'id="m-bench-select"' in html


def test_rust_harness_injects_inside_timed_region_and_renames_tsc_ticks():
    rs = Path("noise-bench/src/main.rs").read_text(encoding="utf-8")
    # busy_wait_ns must occur before start.elapsed() in all 3 benchmark loops, never after
    assert "start.elapsed().as_nanos() as u64 + inject_ns" not in rs
    assert rs.count("busy_wait_ns(inject_ns);") >= 3
    assert "println!(\"elapsed_ns,tsc_ticks\");" in rs
    assert "read_tsc_ticks" in rs


def test_collect_validation_interleaves_and_computes_dynamic_median():
    sh = Path("noise-bench/collect_validation.sh").read_text(encoding="utf-8")
    assert "106000" not in sh
    assert "BASE_NS" in sh
    assert 'for idx in $(seq 1 "$REPS")' in sh
