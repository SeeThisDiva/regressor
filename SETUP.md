# Setup, Docker & Hardware Guide

`regressor` works in two tiers depending on what you want to run:

- **Anywhere (Linux, macOS, Windows — Python 3.11+ only)**: Full statistical engine, SQLite persistence, `data/` historical dataset reproduction, `PyMicroAdapter`, FastAPI dashboard, and the full test suite.
- **Docker or Bare-Metal Linux (Rust toolchain + git history)**: Native `noise-bench` benchmarking across historical `rust-lang/regex` commits (`RegexAdapter`). Dedicated Linux hardware is required if you want CPU isolation (`isolcpus`), fixed clock frequencies, and hardware PMU counters (`perf_event_open`).

The original Study 1 dataset in [`noise-bench/REPORT.md`](noise-bench/REPORT.md) was collected on a shared single-vCPU cloud VM without CPU pinning or governor access—that lack of hardware isolation caused every false positive in the sequential run. If you are on macOS or Windows and want to run the native Linux harness, run inside Docker or a Linux VM rather than attempting to pin the host OS.

---

## 1. Local Python Setup (No Rust or Docker Required)

```bash
git clone https://github.com/SeeThisDiva/regressor.git
cd regressor
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Verify your environment and explore the portable study dataset:

```bash
python regressor.py init
python regressor.py import-data data/regex_history.json.gz
python regressor.py batch regex --verify-legacy
python regressor.py validate-adapter PyMicroAdapter --reps 20
python regressor.py serve --port 8000
```

---

## 2. Containerized Rust Harness (Docker)

[`Dockerfile`](Dockerfile) builds a reproducible, non-root container (`regressor`, UID `10001`) at `/work/regressor` with `rust:1.99-slim-bookworm`, Python 3, `noise-bench` compiled in release mode, `rust-lang/regex` cloned into `/work/regressor/regex` (full git history retained, default `REGEX_SHA=3d79fe92666a9f191d7677ebc123ac165eac200c`), and crates.io dependencies pre-fetched into `/usr/local/cargo` (`CARGO_HOME`) so historical builds can run offline via `--network none`. [`scripts/container_entrypoint.sh`](scripts/container_entrypoint.sh) automatically enables `CARGO_NET_OFFLINE=true` when `REGRESSOR_OFFLINE=1` or when only loopback networking (`--network none`) is present.

> **Why `/work/regressor/regex`?** [`noise-bench/Cargo.toml`](noise-bench/Cargo.toml) declares `regex = { path = "../regex" }`, and `RegexAdapter` defaults to `<repo>/regex`. If you clone `regex` locally outside Docker, clone it directly inside the `regressor` root directory (`git clone https://github.com/rust-lang/regex.git`).

### Helper Script (`scripts/run_in_container.sh`) & Docker Compose

Use [`scripts/run_in_container.sh`](scripts/run_in_container.sh) (supports `--build`, `--offline`, `--cpuset`, `--results-dir`, `--no-tty`, `--dry-run`) or [`docker-compose.yml`](docker-compose.yml) (`regressor` and `regressor-offline` services, both hardened with `user: "10001:10001"`, `cap_drop: ALL`, `no-new-privileges:true`, and zero host credential mounts):

```bash
mkdir -p results
chmod 0777 results   # or match UID 10001 so the non-root container can write

# Build image and launch interactive shell:
./scripts/run_in_container.sh --build

# Run an offline interleaved comparison pinned to cores 2 and 3:
./scripts/run_in_container.sh --offline --cpuset 2,3 -- \
  python3 regressor.py compare-interleaved --adapter RegexAdapter \
    --repo /work/regressor/regex --base 4733e28 --cand 3d79fe9 --pairs 12

# Or via Docker Compose (offline profile uses network_mode: none + CARGO_NET_OFFLINE=true):
docker compose --profile offline run --rm regressor-offline
```

Equivalent direct `docker` invocations:

```bash
docker build -t regressor:latest -f Dockerfile .
docker run --rm -it --init \
  --user 10001:10001 \
  --cap-drop ALL --security-opt no-new-privileges:true \
  --cpuset-cpus="2,3" \
  --network none -e CARGO_NET_OFFLINE=true -e REGRESSOR_OFFLINE=1 \
  -v "$(pwd)/results:/work/regressor/noise-bench/results" \
  regressor:latest
```

Inside the container:

```bash
python3 regressor.py init
python3 regressor.py validate-adapter RegexAdapter --reps 20
```

> **Offline vs. network builds**: `Dockerfile` runs `cargo fetch && cargo build --release` for the default `REGEX_SHA`. Commits whose `Cargo.lock` matches cached crates build cleanly under `--network none`; commits introducing new crate dependencies require an initial network-enabled pass (e.g., without `--offline`) before locking down `--network none`.

### Container & Continuous GitHub Actions Workflows

- **PR / Push Smoke Check ([`.github/workflows/container.yml`](.github/workflows/container.yml))**: Builds `Dockerfile` on `ubuntu-latest`, verifies UID `10001`, executes an offline 2-commit interleaved check and 2-commit incremental collection via `scripts/continuous_collect.py`, and uploads `container-smoke-results`.
- **Opt-In Continuous Collection ([`.github/workflows/continuous.yml`](.github/workflows/continuous.yml) & [`scripts/continuous_collect.py`](scripts/continuous_collect.py))**: Runs on `workflow_dispatch` or daily `schedule` (when repository variable `REGRESSOR_CONTINUOUS_ENABLED == 'true'`), fetching new `rust-lang/regex` commits after the latest recorded `.json.gz` entry, profiling each commit in an isolated worktree, running `batch --fdr by` + E-Divisive change-points, and optionally committing updates (`inputs.commit_dataset` / `REGRESSOR_CONTINUOUS_COMMIT == 'true'`).
- **PR Check Action ([`action.yml`](action.yml) & [`examples/perf-check.yml`](examples/perf-check.yml))**: Composite action supporting `benchmark`, `pairs`, `iters`, `warmup`, `canary-reps`, `require-ci-bound`, `no-fail-on-env-suspect`, `fail-on-regression`, and `workdir` inputs, emitting `report` and `json-report` outputs even when `--fail-on-regression` exits non-zero.

> **Verification Scope Note**: On the Windows 11 development host (which lacks Docker, WSL, and bare-metal Linux), `Dockerfile`, `docker-compose.yml`, `.github/workflows/container.yml`, `.github/workflows/continuous.yml`, `action.yml`, and shell scripts were validated structurally and via `--dry-run` / `actionlint-py` / `tests/test_platform_ci.py` (with `continuous_collect.py` tested against a temp git repo and stub adapter). Actual Docker image builds and CI workflow runs were not executed locally.

---

## 3. Bare-Metal Linux CPU Isolation

To control timing variance on a dedicated Linux host, isolate cores from the OS scheduler rather than relying on `taskset` alone. [`scripts/pin_host.sh`](scripts/pin_host.sh) automates inspection (`--status`), idempotent tuning (`--apply`), and restoration (`--restore`), with `--dry-run` safe on any OS:

```bash
./scripts/pin_host.sh --status --cpus 2,3
./scripts/pin_host.sh --dry-run --apply --cpus 2,3 --freq 3.0GHz --offline-cpu 3
sudo ./scripts/pin_host.sh --apply --cpus 2,3 --freq 3.0GHz --offline-cpu 3
# Restore dynamic governor & turbo after benchmarking:
sudo ./scripts/pin_host.sh --restore --cpus 2,3 --offline-cpu 3
```

Manual steps implemented by (or paired with) [`scripts/pin_host.sh`](scripts/pin_host.sh):

1. **Isolate cores in GRUB** (`/etc/default/grub`, persistent across reboots; `pin_host.sh` never edits GRUB automatically), then run `sudo update-grub` and reboot:
   ```text
   isolcpus=2,3 nohz_full=2,3 rcu_nocbs=2,3
   ```
   Verify after reboot:
   ```bash
   cat /proc/cmdline | grep isolcpus
   ```

2. **Pin CPU frequency and disable turbo boost** (handled idempotently by `pin_host.sh --apply`):
   ```bash
   sudo apt install linux-tools-common linux-tools-$(uname -r)
   sudo cpupower frequency-set -g performance
   sudo cpupower frequency-set -d 3.0GHz -u 3.0GHz  # match your CPU's base clock
   echo 1 | sudo tee /sys/devices/system/cpu/intel_pstate/no_turbo   # Intel
   # AMD equivalent: echo 0 | sudo tee /sys/devices/system/cpu/cpufreq/boost
   ```

3. **Disable the hyperthreading sibling** of your benchmark core (`--offline-cpu N`, `N >= 1`; `pin_host.sh` refuses to offline CPU `0`):
   ```bash
   echo 0 | sudo tee /sys/devices/system/cpu/cpu3/online   # if cpu3 shares a physical core with cpu2
   ```

4. **Run pinned and sanity-check the baseline CV**:
   ```bash
   taskset -c 2 nice -n -20 ./target/release/noise-bench find_iter_userid 2000 200

   export NOISE_BENCH_DIR=/work/regressor/noise-bench
   cd "$NOISE_BENCH_DIR"
   ./run_noise_study.sh && python3 analyze_noise.py
   ./collect_validation.sh
   ```
   Compare your baseline coefficients of variation against the Study 1 sandbox numbers in [`noise-bench/REPORT.md`](noise-bench/REPORT.md) (`1.38%` on `compile_moderate`, `10.54%` on `find_iter_userid`, `1.89%` on `is_match_status`). If `find_iter_userid` is not clearly below `10.5%`, fix CPU isolation before running historical batches.

---

## 4. Running the Raw Rust Harness Directly

`noise-bench` compiles **25 benchmarks** (3 legacy workloads plus 22 `BurntSushi/rebar`-derived benchmarks; see [`noise-bench/BENCHMARKS.md`](noise-bench/BENCHMARKS.md)):

```bash
export REGEX_REPO=/work/regressor/regex
export NOISE_BENCH_DIR=/work/regressor/noise-bench
cd "$NOISE_BENCH_DIR"
python3 harness/run_commit.py <sha> --reps 20 --iters 2000 --warmup 200
# Study 3 full 51-commit x 25-benchmark collection (per-benchmark iters in harness/study3_iters.json):
python3 harness/run_study3.py --reps 15 --iters 1000 --warmup 100
# Or run Study 1 commit list in harness/commits.txt:
./run_batch.sh 1 999
python3 analyze/run_batch_analysis.py
```

If you collected raw commit directories in `noise-bench/results/commits/`, you can import them into SQLite instead of `data/regex_history.json.gz`, and print study summaries or export a static dashboard site:

```bash
python regressor.py import-legacy
python regressor.py batch regex
python regressor.py analyze regex 16d47c5 0a446ec
python regressor.py summary regex --study study3
python regressor.py export-site ./site
```

---

## 5. Software Capabilities, PMU Telemetry & Windows Profiling

### What Runs Anywhere vs. Bare-Metal Linux

| Capability | Standard Laptop / CI Runner | Dedicated Bare-Metal Linux (`isolcpus`) |
|---|---|---|
| Statistical engine, SQLite DB, Web UI, `PyMicroAdapter`, tests | Full support | Full support |
| Interleaved A/B (`compare-interleaved`), canary drift check, `bisect` | Full support | Full support (tighter MDE) |
| Native Rust historical builds (`RegexAdapter`) | Docker or local Rust toolchain | Native with pinned frequency & isolated cores |
| Hardware retired instructions (`PERF_COUNT_HW_INSTRUCTIONS`) | `pmu_status: "UNAVAILABLE"` | Available via `perf_event_open` |
| Differential profiling without Linux `perf` | Windows user-mode `win_profile.py` (Win32 `SuspendThread` DWARF + `llvm-objdump` static insns) | `perf record` / hardware PMU |

### How PMU, ETW & User-Mode Profiling Work

1. **Linux `perf_event_open` (`PERF_COUNT_HW_INSTRUCTIONS`)**: Counts retired instructions directly via hardware PMU MSRs (`IA32_FIXED_CTR0`), independent of CPU clock frequency or thermal throttling. In the unprivileged Study 1 VM, hardware PMU counters returned `<not supported>`, so `0a446ec` was triaged with software `cpu-clock` sampling flamegraphs (`+0.3%` CPU sample delta).
2. **Windows Elevation-Free Profiling (`noise-bench/analyze/win_profile.py`)**: On Windows hosts without Administrator elevation, ETW-based tools (`blondie`, `samply`) fail with `Access Denied` on the kernel PMC/ETW session. [`noise-bench/analyze/win_profile.py`](noise-bench/analyze/win_profile.py) replaces ETW with user-mode Win32 `SuspendThread` sampling + PE `.pdata`/`.xdata` unwinding + `llvm-objdump` DWARF inline attribution (`sample` mode) and static disassembly instruction attribution (`insn` mode; requires `rustup component add llvm-tools`). See [`noise-bench/profiles/PROFILING.md`](noise-bench/profiles/PROFILING.md).
3. **User-space x86 `_rdtsc`**: Reads the invariant Time Stamp Counter across platforms without root privileges (used alongside wall-clock timings during local `8f5d947` ablation verification).
4. **Cloud VMs without vPMU (`pmu_status: "UNAVAILABLE"`)**: Standard cloud VMs and Windows hosts cannot read hardware PMU MSRs. `regressor` never fabricates counters: it records `pmu_status: "UNAVAILABLE"` and relies on $3\times\text{CV}$ noise-floor gating, interleaved A/B execution, and canary drift correlation.
5. **Standalone Upstream Repros (`reports/upstream/`)**: Once an issue is confirmed, [`noise-bench/analyze/stamp_repro.py`](noise-bench/analyze/stamp_repro.py) stamps [`reports/upstream/repro-template/`](reports/upstream/repro-template/) into a standalone two-revision Cargo package (`reports/upstream/<sha>/repro/`) that any maintainer can run without `regressor`.
