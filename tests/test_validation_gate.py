"""
tests/test_validation_gate.py
Deterministic checks of the synthetic validation gate using a seeded simulated adapter
(no wall-clock timing involved).
"""

import numpy as np

from adapters.base import BaseAdapter
from core.models import BuildResult
from core.validation import validate_adapter_synthetic


class SimAdapter(BaseAdapter):
    """One 'iteration' per run: base + injected + gaussian noise. `honors_injection=False`
    models an adapter whose injection hook does nothing (the failure the gate must catch)."""

    def __init__(self, base=10_000.0, cv=0.01, honors_injection=True, amplify=1.0, seed=0):
        self.base, self.cv, self.honors = base, cv, honors_injection
        self.amplify, self.rng = amplify, np.random.default_rng(seed)

    def list_benchmarks(self):
        return ["sim"]

    def build(self, commit_ref, workdir=None):
        return BuildResult(ok=True, seconds=0.0, artifact=commit_ref)

    def run(self, bench_name, iters, warmup, inject_ns=0, artifact=None):
        extra = (inject_ns * self.amplify) if self.honors else 0
        return [float(self.rng.normal(self.base, self.cv * self.base) + extra)]


def test_quiet_host_passes_even_though_the_one_percent_injection_is_detected():
    r = validate_adapter_synthetic(SimAdapter(cv=0.002, seed=1), "sim", reps=25)
    assert r.large_injection_flagged
    assert r.noise_floor_pct < 1.0           # quiet: floor is below the 1% injection
    assert r.all_passed                       # previously this configuration FAILED the gate


def test_noisy_host_passes_by_gating_the_small_injection():
    r = validate_adapter_synthetic(SimAdapter(cv=0.02, seed=2), "sim", reps=25)
    assert r.large_injection_flagged and r.small_injection_gated and r.all_passed


def test_adapter_that_ignores_injection_fails_the_gate():
    r = validate_adapter_synthetic(SimAdapter(cv=0.01, honors_injection=False, seed=3), "sim", reps=25)
    assert not r.large_injection_flagged and not r.all_passed


def test_adapter_that_amplifies_injection_5x_fails_the_gate():
    for cv in (0.005, 0.002):
        r = validate_adapter_synthetic(SimAdapter(cv=cv, amplify=5.0, seed=4), "sim", reps=25)
        assert not r.small_injection_gated and not r.all_passed
