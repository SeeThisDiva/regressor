# Contributing to `regressor`

Thank you for your interest in contributing! This guide covers local development setup, verification checks, and adding new benchmark adapters.

## Development Setup

Python 3.11+ is required (see [`pyproject.toml`](pyproject.toml)). You do not need Rust or Docker to run the statistical engine, API/UI, `PyMicroAdapter`, or the test suite.

```bash
python -m venv .venv
# Linux / macOS:
source .venv/bin/activate
# Windows (PowerShell):
# .venv\Scripts\Activate.ps1

pip install -e ".[dev]"
```

For building and running native Rust benchmarks (`noise-bench/` / `RegexAdapter`), see [`SETUP.md`](SETUP.md).

## Verification Before Opening a PR

Run lint, unit/integration tests, and the end-to-end study reproduction check:

```bash
ruff check .
pytest -p no:cacheprovider
sh scripts/verify.sh
```

On Windows without Git Bash, run `ruff check .` and `pytest -p no:cacheprovider` directly. Always use a temporary `--db` path when testing CLI commands locally so `regressor.db` is not left in your working tree.

## Adding a New Benchmark Adapter

1. Subclass `BaseAdapter` in [`adapters/`](adapters/base.py) and implement:
   - `list_benchmarks() -> list[str]`
   - `build(commit_ref, workdir=None) -> BuildResult` (support isolated worktrees when `workdir` is provided so `compare-interleaved` and `bisect` can alternate builds)
   - `run(bench_name, iters, warmup, inject_ns=0, artifact=None) -> list[float]` (inject `inject_ns` via real CPU work inside the timed loop, e.g. `busy_wait_ns`)
2. Register the adapter in `ADAPTER_REGISTRY` in [`regressor.py`](regressor.py).
3. Add a project manifest under [`projects/`](projects/regex.toml) (`projects/<name>.toml`).
4. Verify the 3-point synthetic ground-truth gate passes before running on real git history:
   ```bash
   python regressor.py validate-adapter <YourAdapter> --reps 20
   ```

## Guidelines

- **Keep statistical claims grounded**: Do not fabricate hardware counters (`pmu_status: "UNAVAILABLE"` when unavailable) or relax statistical thresholds to hide noise.
- **Keep paths portable**: Never commit absolute local paths, local filesystem URIs, or personal machine identifiers in docs, tests, or result artifacts.
- **Update docs & tests together**: CLI and doc invariants are verified automatically in [`tests/test_stage5_api_hardening.py`](tests/test_stage5_api_hardening.py).
