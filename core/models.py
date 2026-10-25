"""
core/models.py
Data models and typed contracts for the Generalized Performance Regression Framework.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class BuildResult:
    ok: bool
    seconds: float
    log_tail: str = ""
    artifact: Optional[str] = None  # path/identifier of the built benchmark binary


@dataclass
class RunResult:
    benchmark: str
    rep_index: int
    sample_file_path: str
    median_ns: float
    pmu_metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ComparisonResult:
    base_sha: str
    cand_sha: str
    benchmark: str
    p_value: float
    shift_pct: float
    noise_floor_pct: float
    verdict: str  # 'flag' or 'ok'
    fdr_significant: bool = False
    attribution: str = "NO_REGRESSION"
    resolution_status: str = "unreviewed"  # 'unreviewed' | 'confirmed' | 'false_positive'
    resolution_note: str = ""
    canary_status: str = "NOT_RECORDED"  # 'OK' | 'ENVIRONMENT_SUSPECT' | 'NOT_RECORDED'
    pmu_status: str = "UNAVAILABLE"  # only set otherwise if real hardware counters were read


@dataclass
class ProjectConfig:
    name: str
    repo_url: str
    adapter_name: str
    build_cmd: str
    benchmarks: List[str]
    source_paths: List[str] = field(default_factory=lambda: ["src/**"])
    noise_floor_multiplier: float = 3.0
    canary_threshold_pct: float = 2.5
    raw_config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SyntheticValidationResult:
    adapter_name: str
    benchmark: str
    true_negative_ok: bool
    true_negative_p_value: float
    large_injection_flagged: bool
    large_injection_p_value: float
    large_injection_shift_pct: float
    small_injection_gated: bool
    small_injection_p_value: float
    small_injection_shift_pct: float
    noise_floor_pct: float
    all_passed: bool
