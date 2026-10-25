"""
tests/test_stage1_stats.py
Statistical-correctness regressions found in the Stage 1 review. All seeded and deterministic.
"""

import numpy as np
import pytest

from core.canary import CanaryBenchmark
from core.detector import compare_distributions, order_trend
from core.samples import parse_samples
from core.series_detector import _pairwise_abs, _split_stats, detect_series_changepoints_edivisive, energy_distance_1d

# ---------- E-Divisive ----------

def test_split_stats_matches_reference_definition():
    x = np.random.default_rng(0).normal(size=17)
    m = 3
    fast = _split_stats(_pairwise_abs(x), m)
    slow = [(t * (17 - t) / 17) * energy_distance_1d(x[:t], x[t:]) for t in range(m, 17 - m + 1)]
    assert np.allclose(fast, slow)


def test_edivisive_false_positive_rate_on_pure_noise():
    """The previous implementation compared against the permuted statistic at the OBSERVED
    split, ignoring the max over splits: ~37% false positives at nominal 5%. Guard it."""
    rng = np.random.default_rng(7)
    trials, hits = 120, 0
    for t in range(trials):
        series = rng.normal(1000, 10, size=27)
        if detect_series_changepoints_edivisive([str(i) for i in range(27)], [[v] for v in series],
                                                permutations=99, seed=t):
            hits += 1
    assert hits / trials < 0.15, f"FPR {hits / trials:.1%} (nominal 5%)"


def test_edivisive_finds_injected_step_and_tags_session_break():
    rng = np.random.default_rng(3)
    level = np.r_[np.full(14, 1000.0), np.full(13, 1100.0)]
    runs = [list(rng.normal(lv, 8, size=20)) for lv in level]
    cps = detect_series_changepoints_edivisive([f"c{i}" for i in range(27)], runs, known_breaks=[14])
    assert [c["index"] for c in cps] == [14]
    assert cps[0]["session_break"] is True and cps[0]["exceeds_noise_floor"] is True
    assert cps[0]["shift_pct"] == pytest.approx(10.0, abs=1.0)


def test_edivisive_no_session_tag_when_break_elsewhere():
    rng = np.random.default_rng(3)
    level = np.r_[np.full(14, 1000.0), np.full(13, 1100.0)]
    runs = [list(rng.normal(lv, 8, size=20)) for lv in level]
    cps = detect_series_changepoints_edivisive([f"c{i}" for i in range(27)], runs, known_breaks=[5])
    assert cps and cps[0]["session_break"] is False


# ---------- strict sample parsing ----------

def test_parse_samples_accepts_floats_and_scientific_notation():
    assert parse_samples("1\n2.5\n3e2\n", expected=3) == [1.0, 2.5, 300.0]


@pytest.mark.parametrize("text,expected", [("", None), ("1 2 oops 4", None), ("1 2 3", 4), ("1 nan 3", None)])
def test_parse_samples_rejects_bad_output(text, expected):
    with pytest.raises(ValueError):
        parse_samples(text, expected=expected)


# ---------- canary ----------

def test_canary_cold_start_outlier_does_not_blind_the_check():
    """One slow first sample (real behaviour) must not widen the allowed-noise band."""
    base = [4970.0, 3430.0, 3370.0, 3360.0, 3460.0, 3390.0, 3410.0, 3490.0, 3410.0, 3450.0]
    drifted = [x * 1.20 for x in base[1:]] + [3400.0 * 1.2]
    assert CanaryBenchmark.evaluate_drift(base, drifted)["status"] == "ENVIRONMENT_SUSPECT"


def test_canary_min_drift_floor_applies():
    base = [1000.0, 1000.5, 999.5, 1000.2, 999.8] * 3
    small = [x * 1.015 for x in base]            # +1.5%: under the 2.5% floor even on a quiet baseline
    assert CanaryBenchmark.evaluate_drift(base, small)["status"] == "OK"
    assert CanaryBenchmark.evaluate_drift(base, small, min_drift_pct=1.0)["status"] == "ENVIRONMENT_SUSPECT"


def test_canary_max_allowed_noise_cap_catches_10pct_shift():
    """Even if baseline canary samples have high MAD spread (~6% CV), the 5% cap must
    flag a +10.84% shift as ENVIRONMENT_SUSPECT rather than letting it pass as OK."""
    rng = np.random.default_rng(42)
    base = list(rng.normal(1000.0, 65.0, size=15))
    cand = [x * 1.1084 for x in base]
    res = CanaryBenchmark.evaluate_drift(base, cand)
    assert res["allowed_noise_pct"] <= 5.0
    assert res["status"] == "ENVIRONMENT_SUSPECT"
    assert res["is_drifted"] is True


# ---------- within-sample trend diagnostic ----------

def test_order_trend_detects_monotonic_ramp_but_not_noise():
    rng = np.random.default_rng(0)
    ramp = 1000 + np.arange(20) * 3.0 + rng.normal(0, 1, 20)
    noise = rng.normal(1000, 5, 20)
    assert order_trend(ramp)["rho"] > 0.9 and order_trend(ramp)["p"] < 0.001
    assert abs(order_trend(noise)["rho"]) < 0.6
    assert order_trend(np.full(20, 5.0)) == {"rho": None, "p": None}


def test_trend_is_reported_without_changing_the_verdict():
    rng = np.random.default_rng(1)
    base = 1000 + np.arange(20) * 2.0 + rng.normal(0, 1, 20)
    cand = base + 200
    r = compare_distributions(base, cand)
    assert r["verdict"] == "flag" and r["drift_suspect"] is True
    assert "trend" in r["resolution_note"]
