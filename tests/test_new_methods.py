"""
tests/test_new_methods.py
Tests for interleaved A/B, drift-aware FPR, session gaps, bisection and adapter honesty.
Timing tests use PyMicroAdapter: real measurements, injected delay is real busy-wait.
"""

import numpy as np
import pytest
from scipy import stats

from adapters.pymicro_adapter import PyMicroAdapter
from adapters.regex_adapter import RegexAdapter
from core.bisect import bisect_builds
from core.interleaved import analyze_paired, min_wilcoxon_p, run_interleaved, walsh_hodges_lehmann
from core.power import aa_random_split, binom_ci, evaluate_power_curve, null_transition_fpr

# ---------- paired statistics ----------

def test_paired_wilcoxon_matches_scipy():
    rng = np.random.default_rng(1)
    a = rng.normal(1000, 20, 15)
    b = a * 1.03 + rng.normal(0, 5, 15)
    r = analyze_paired(list(a), list(b), alpha=0.01, min_effect_pct=1.0)
    d = 100 * (b - a) / a
    assert r["p_value"] == pytest.approx(stats.wilcoxon(d).pvalue, rel=1e-9)
    assert r["verdict"] == "flag"
    lo, hi = r["shift_ci95_pct"]
    assert lo <= r["shift_pct"] <= hi


def test_walsh_hodges_lehmann_known_values():
    # Walsh averages of [1,2,3]: 1,1.5,2,2,2.5,3 -> median 2
    assert walsh_hodges_lehmann(np.array([1.0, 2.0, 3.0])) == pytest.approx(2.0)


def test_paired_cancels_common_drift():
    # Both builds drift together by up to 30%; the true difference is +2%.
    drift = np.linspace(1.0, 1.3, 20)
    a = 1000 * drift
    b = 1020 * drift
    r = analyze_paired(list(a), list(b), min_effect_pct=1.0)
    assert r["shift_pct"] == pytest.approx(2.0, abs=1e-6)
    assert r["verdict"] == "flag"


def test_min_effect_gate_blocks_tiny_but_significant_shift():
    a = np.full(20, 1000.0) + np.arange(20) * 0.01
    b = a * 1.002  # +0.2%, perfectly consistent -> p tiny
    r = analyze_paired(list(a), list(b), min_effect_pct=1.0)
    assert r["p_value"] < 0.01 and r["verdict"] == "ok"


def test_refuses_pair_counts_that_cannot_reach_alpha():
    assert min_wilcoxon_p(7) > 0.01 > min_wilcoxon_p(8)
    with pytest.raises(ValueError):
        run_interleaved(PyMicroAdapter(), "json_loads", "A", "B", pairs=6)


# ---------- interleaved runs on real timings ----------

def test_interleaved_same_build_not_flagged():
    ad = PyMicroAdapter()
    ad.run("json_loads", 300, 30)
    r = run_interleaved(ad, "json_loads", "A", "A", pairs=20, iters=300, warmup=30, seed=0)
    assert r["verdict"] == "ok"
    assert sorted(set(r["order"])) <= ["AB", "BA"]


def test_interleaved_detects_real_extra_work_between_builds():
    # 2000 ns busy-wait per iteration in build "slow" (~9 ms extra wall time across 20 pairs):
    # clears Python 3.11 sys.settrace coverage overhead and shared-runner vCPU jitter in CI.
    ad = PyMicroAdapter({"slow": 2000})
    ad.run("json_loads", 300, 30)
    r = run_interleaved(ad, "json_loads", "fast", "slow", pairs=20, iters=300, warmup=30, seed=0)
    assert r["verdict"] == "flag" and r["shift_pct"] > 5


# ---------- bisection ----------

def test_bisect_finds_culprit_with_real_timings():
    commits = [f"c{i:02d}" for i in range(12)]
    ad = PyMicroAdapter({c: (2000 if i >= 7 else 0) for i, c in enumerate(commits)})
    ad.run("json_loads", 300, 30)
    res = bisect_builds(ad, commits, "json_loads", pairs=20, iters=300, warmup=30, log=lambda s: None)
    assert res["reproduced"] and res["culprit"] == "c07" and res["last_good"] == "c06"
    assert res["builds"] <= 6  # good + bad + ~log2(12) probes


def test_bisect_stops_when_bad_does_not_reproduce():
    commits = [f"c{i:02d}" for i in range(8)]
    res = bisect_builds(PyMicroAdapter(), commits, "json_loads", pairs=20, iters=300, warmup=30,
                        log=lambda s: None)
    assert res["reproduced"] is False and res["culprit"] is None


# ---------- false-positive accounting ----------

def test_binom_ci_matches_scipy():
    ci = stats.binomtest(4, 21).proportion_ci(method="exact")
    assert binom_ci(4, 21) == [round(100 * ci.low, 2), round(100 * ci.high, 2)]


def test_null_transition_fpr_splits_by_session_gap():
    rows = [
        {"cand_subject": "doc: x", "verdict": "flag", "fdr_significant": True, "session_gap_min": 201.0,
         "benchmark": "b1", "cand_sha": "aaa", "shift_pct": -20.0},
        {"cand_subject": "doc: y", "verdict": "ok", "fdr_significant": False, "session_gap_min": 0.1,
         "benchmark": "b1", "cand_sha": "bbb", "shift_pct": 0.3},
        {"cand_subject": "automata: real change", "verdict": "flag", "fdr_significant": True,
         "session_gap_min": 0.1, "benchmark": "b1", "cand_sha": "ccc", "shift_pct": 9.0},
    ]
    r = null_transition_fpr(rows)
    assert r["all"]["n"] == 2 and r["all"]["flags"] == 1
    assert r["within_session"]["flags"] == 0
    assert r["across_session_break"]["flags"] == 1


def test_aa_random_split_on_iid_noise_is_rare():
    rng = np.random.default_rng(3)
    r = aa_random_split(list(rng.normal(1000, 20, 50)), trials=300)
    assert r["fpr_pct"] <= 2.0


def test_power_increases_with_effect_size():
    rng = np.random.default_rng(4)
    pw = evaluate_power_curve(list(rng.normal(1000, 10, 50)), effect_sizes_pct=(0.5, 10.0),
                              rep_counts=(20,), trials_per_point=100)
    g = pw["power_grid"]["N=20"]
    assert g["+10%"] > g["+0.5%"]


# ---------- adapter honesty ----------

def test_regex_adapter_has_no_silent_fallback(tmp_path):
    ad = RegexAdapter(noise_bench_dir=str(tmp_path))
    with pytest.raises(FileNotFoundError):
        ad.run("compile_moderate", 10, 1)


def test_session_gap_minutes():
    from regressor import session_gap_minutes
    a = {"run_finished_utc": "2026-08-14T00:41:12+00:00"}
    b = {"run_started_utc": "2026-08-14T04:02:14+00:00"}
    assert session_gap_minutes(a, b) == pytest.approx(201.0, abs=0.1)
    assert session_gap_minutes({"run_finished_utc": ""}, b) is None
