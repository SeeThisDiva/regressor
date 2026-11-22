"""
tests/test_layout_floor.py
Tests for post-hoc offline layout-floor calibration on Study 3 (`data/regex_study3_history.json.gz`),
verifying non-circularity (disjoint 2-fold calibration/evaluation splits), exact before/after
metrics, `64ad0b6` detection, synthetic injection sensitivity, and doc consistency.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pytest

from core.detector import compare_distributions
from core.layout_floor import evaluate_study3_layout_floor, is_null_control_subject

ROOT = Path(__file__).resolve().parent.parent
STUDY3_DATA = ROOT / "data" / "regex_study3_history.json.gz"
STUDY3_META = ROOT / "noise-bench" / "harness" / "commits_study3.json"
TRIAGE_PATH = ROOT / "projects" / "regex.triage.json"


@pytest.fixture(scope="module")
def layout_floor_result() -> Dict[str, Any]:
    return evaluate_study3_layout_floor(STUDY3_DATA, triage_path=TRIAGE_PATH)


def test_is_null_control_subject_matches_study3_manifest_29_of_50() -> None:
    with gzip.open(STUDY3_DATA, "rt", encoding="utf-8") as fh:
        commits = json.load(fh)["commits"]
    manifest = {c["sha"]: bool(c["is_null_control"]) for c in json.loads(STUDY3_META.read_text(encoding="utf-8"))["commits"]}

    matched = 0
    for c in commits[1:]:
        pred = is_null_control_subject(c["subject"])
        assert pred == manifest[c["sha"]], f"Mismatch for {c['short_sha']}: {c['subject']}"
        if pred:
            matched += 1
    assert matched == 29


def test_compare_distributions_min_noise_floor_pct_gates_small_shifts() -> None:
    rng = np.random.default_rng(7)
    base = rng.normal(1000.0, 2.0, size=15)
    cand = base * 1.03  # +3.0% shift, well above tight ~0.6% 3*CV floor

    default_res = compare_distributions(base, cand)
    zero_floor_res = compare_distributions(base, cand, min_noise_floor_pct=0.0)
    assert default_res == zero_floor_res
    assert default_res["verdict"] == "flag"

    suppressed = compare_distributions(base, cand, min_noise_floor_pct=5.0)
    assert suppressed["verdict"] == "ok"
    assert suppressed["noise_floor_pct"] == pytest.approx(5.0, abs=1e-9)

    big_cand = base * 1.12
    still_flagged = compare_distributions(base, big_cand, min_noise_floor_pct=5.0)
    assert still_flagged["verdict"] == "flag"


def test_layout_floor_folds_are_disjoint_and_cover_all_29_nulls(layout_floor_result: Dict[str, Any]) -> None:
    fold_a = layout_floor_result["folds"]["fold_a"]
    fold_b = layout_floor_result["folds"]["fold_b"]

    cal_a = set(fold_a["cal_null_indices"])
    eval_a = set(fold_a["eval_indices"])
    cal_b = set(fold_b["cal_null_indices"])
    eval_b = set(fold_b["eval_indices"])

    assert not (cal_a & eval_a)
    assert not (cal_b & eval_b)
    assert not (cal_a & cal_b)
    assert len(cal_a) == 14 and len(cal_b) == 15
    assert cal_a | cal_b == set(fold_a["eval_null_indices"]) | set(fold_b["eval_null_indices"])
    assert len(cal_a | cal_b) == 29


def test_layout_floor_pins_exact_before_after_and_64ad0b6_results(layout_floor_result: Dict[str, Any]) -> None:
    base = layout_floor_result["full_baseline"]
    assert base["comparisons"] == 1250
    assert base["flags"] == 371
    assert base["heldout_null_flags"] == 218
    assert base["heldout_null_comparisons"] == 725
    assert base["cloudflare_64ad0b6_flagged"] is True

    fa = layout_floor_result["folds"]["fold_a"]
    assert fa["before"]["comparisons"] == 900
    assert fa["before"]["flags"] == 267
    assert fa["before"]["heldout_null_flags"] == 114
    assert fa["before"]["heldout_null_comparisons"] == 375
    assert fa["before"]["heldout_null_fpr_pct"] == pytest.approx(30.40, abs=1e-9)
    assert fa["before"]["heldout_null_wilson_ci95_pct"] == [25.96, 35.23]
    assert fa["after"]["flags"] == 24
    assert fa["after"]["heldout_null_flags"] == 10
    assert fa["after"]["heldout_null_fpr_pct"] == pytest.approx(2.67, abs=1e-9)
    assert fa["after"]["heldout_null_wilson_ci95_pct"] == [1.45, 4.84]
    assert fa["after"]["triaged_confirmed"] == 1
    assert fa["after"]["triaged_false_positive"] == 22
    assert fa["after"]["triaged_layout_artifact"] == 1
    assert fa["after"]["triaged_fp_wilson_ci95_pct"] == [74.15, 97.68]
    assert fa["after"]["cloudflare_64ad0b6_flagged"] is True
    assert fa["after"]["cloudflare_64ad0b6_floor_pct"] == pytest.approx(0.421, abs=1e-3)
    assert fa["validation_8pct"] == {"total_benchmarks": 25, "before": 24, "after": 14}

    fb = layout_floor_result["folds"]["fold_b"]
    assert fb["before"]["comparisons"] == 875
    assert fb["before"]["flags"] == 256
    assert fb["before"]["heldout_null_flags"] == 103
    assert fb["before"]["heldout_null_comparisons"] == 350
    assert fb["before"]["heldout_null_fpr_pct"] == pytest.approx(29.43, abs=1e-9)
    assert fb["before"]["heldout_null_wilson_ci95_pct"] == [24.9, 34.41]
    assert fb["after"]["flags"] == 18
    assert fb["after"]["heldout_null_flags"] == 2
    assert fb["after"]["heldout_null_fpr_pct"] == pytest.approx(0.57, abs=1e-9)
    assert fb["after"]["heldout_null_wilson_ci95_pct"] == [0.16, 2.06]
    assert fb["after"]["triaged_confirmed"] == 1
    assert fb["after"]["triaged_false_positive"] == 16
    assert fb["after"]["triaged_layout_artifact"] == 1
    assert fb["after"]["triaged_fp_wilson_ci95_pct"] == [67.2, 96.9]
    assert fb["after"]["cloudflare_64ad0b6_flagged"] is True
    assert fb["after"]["cloudflare_64ad0b6_floor_pct"] == pytest.approx(1.177, abs=1e-3)
    assert fb["validation_8pct"] == {"total_benchmarks": 25, "before": 24, "after": 11}

    oof = layout_floor_result["oof_heldout_nulls"]
    assert oof == {
        "comparisons": 725,
        "before_flags": 217,
        "before_fpr_pct": 29.93,
        "before_wilson_ci95_pct": [26.71, 33.36],
        "after_flags": 12,
        "after_fpr_pct": 1.66,
        "after_wilson_ci95_pct": [0.95, 2.87],
    }

    inj = {row["effect_pct"]: (row["before_detected"], row["after_detected"]) for row in layout_floor_result["heldout_injections"]}
    assert inj == {
        5.0: (562, 233),
        8.0: (617, 346),
        10.0: (645, 417),
        15.0: (686, 531),
        20.0: (700, 581),
        50.0: (719, 693),
        95.0: (723, 723),
    }


def test_docs_match_calibrated_layout_floor_section(layout_floor_result: Dict[str, Any]) -> None:
    report = (ROOT / "noise-bench" / "REPORT.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "## Calibrated layout floor (post hoc)" in report
    oof = layout_floor_result["oof_heldout_nulls"]
    oof_ci = f"[{oof['after_wilson_ci95_pct'][0]:.2f}%, {oof['after_wilson_ci95_pct'][1]:.2f}%]"
    for token in (
        f"{oof['after_flags']}/{oof['comparisons']}",
        f"{oof['after_fpr_pct']:.2f}%",
        oof_ci,
        "267 -> 24",
        "256 -> 18",
        "0.421%",
        "1.177%",
        "24/25 -> 14/25",
        "24/25 -> 11/25",
    ):
        assert token in report, f"REPORT.md missing post-hoc layout floor token: {token!r}"

    assert "Calibrated layout floor (post hoc)" in readme
    assert f"{oof['after_fpr_pct']:.2f}%" in readme
    assert oof_ci in readme
