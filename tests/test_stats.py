"""
tests/test_stats.py
Unit tests for regressor statistical engine, validating against scipy.stats.
"""

import numpy as np
import pytest
from scipy import stats

from core.canary import CanaryBenchmark
from core.detector import (
    bh_fdr_correct,
    compare_distributions,
    hodges_lehmann,
)
from core.series_detector import energy_distance_1d


def test_hodges_lehmann_against_median_diff():
    # Symmetric shift of +100 units
    a = np.array([1000.0, 1010.0, 1020.0, 1030.0, 1040.0])
    b = a + 100.0
    shift = hodges_lehmann(a, b)
    assert pytest.approx(shift, abs=1e-3) == 100.0


def test_mann_whitney_u_matches_scipy():
    rng = np.random.default_rng(123)
    a = rng.normal(1000.0, 20.0, size=20)
    b = rng.normal(1050.0, 20.0, size=20)

    res = compare_distributions(a, b, alpha=0.01)

    # Exact verification against scipy
    _, expected_p = stats.mannwhitneyu(b, a, alternative="two-sided")
    assert pytest.approx(res["p_value"], rel=1e-5) == expected_p
    assert res["statistically_significant"] is True


def test_identical_distributions_yield_no_flag():
    # A/A test: identical data
    a = np.array([2000.0, 2010.0, 2020.0, 1990.0, 1980.0, 2005.0] * 3)
    res = compare_distributions(a, a, alpha=0.01)
    assert res["verdict"] == "ok"
    assert res["shift_pct"] == 0.0


def test_bessel_correction_ddof1():
    # Test Bessel's sample std (ddof=1) vs population std (ddof=0)
    # The ratio is exactly sqrt(N / (N - 1))
    runs = np.array([100.0, 102.0, 98.0, 101.0, 99.0, 103.0, 97.0, 100.0, 102.0, 98.0] * 2) # N=20
    s_sample = np.std(runs, ddof=1)
    s_pop = np.std(runs, ddof=0)
    expected_ratio = np.sqrt(20.0 / 19.0)
    assert pytest.approx(s_sample / s_pop, rel=1e-4) == expected_ratio


def test_benjamini_hochberg_fdr_control():
    # 10 tests, 2 truly small p-values, 8 noise p-values
    comps = [
        {"p_value": 0.0001, "verdict": "flag"},
        {"p_value": 0.002, "verdict": "flag"},
        {"p_value": 0.08, "verdict": "ok"},
        {"p_value": 0.15, "verdict": "ok"},
        {"p_value": 0.22, "verdict": "ok"},
        {"p_value": 0.45, "verdict": "ok"},
        {"p_value": 0.60, "verdict": "ok"},
        {"p_value": 0.72, "verdict": "ok"},
        {"p_value": 0.85, "verdict": "ok"},
        {"p_value": 0.99, "verdict": "ok"},
    ]
    bh_fdr_correct(comps, alpha=0.05)
    assert comps[0]["fdr_significant"] is True
    assert comps[1]["fdr_significant"] is True
    assert comps[2]["fdr_significant"] is False


def test_canary_drift_detection():
    # Invariant canary should evaluate to OK on normal noise, and ENVIRONMENT_SUSPECT on 20% drift
    base = [5000.0, 5020.0, 4980.0, 5010.0, 4990.0] * 3
    cand_norm = [5010.0, 4990.0, 5005.0, 5015.0, 4985.0] * 3
    cand_drift = [x * 1.25 for x in base] # +25% drift

    eval_norm = CanaryBenchmark.evaluate_drift(base, cand_norm)
    assert eval_norm["status"] == "OK"
    assert eval_norm["is_drifted"] is False

    eval_drift = CanaryBenchmark.evaluate_drift(base, cand_drift)
    assert eval_drift["status"] == "ENVIRONMENT_SUSPECT"
    assert eval_drift["is_drifted"] is True


def test_energy_distance_properties():
    # Energy distance between identical distributions is 0
    a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert pytest.approx(energy_distance_1d(a, a), abs=1e-5) == 0.0

    # Energy distance between shifted distributions is strictly positive
    b = a + 5.0
    assert energy_distance_1d(a, b) > 0.0


