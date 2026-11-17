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

[`Dockerfile`](Dockerfile) builds a reproducible container at `/work/regressor` with Rust 1.82, Python 3, `noise-bench` compiled in release mode, and `rust-lang/regex` cloned into `/work/regressor/regex` (pinned to Study 1 commit `4733e28` with full git history retained).

> **Why `/work/regressor/regex`?** [`noise-bench/Cargo.toml`](noise-bench/Cargo.toml) declares `regex = { path = "../regex" }`, and `RegexAdapter` defaults to `<repo>/regex`. If you clone `regex` locally outside Docker, clone it directly inside the `regressor` root directory (`git clone https://github.com/rust-lang/regex.git`).

Build and launch the container with a bind-mounted results directory:

```bash
docker build -t regex-noise-bench -f Dockerfile .
mkdir -p results
docker run --rm -it \
  -v "$(pwd)/results:/work/regressor/noise-bench/results" \
  regex-noise-bench
```

Inside the container:

```bash
python3 regressor.py init
python3 regressor.py validate-adapter RegexAdapter --reps 20
```

The image only pre-caches Cargo crates for the pinned commit (`4733e28`). Other commits are built in isolated worktrees and may fetch different crate versions on first build, so run your initial build pass with network enabled. Once crates are cached, lock down CPU cores and disable networking so untrusted `build.rs` scripts cannot reach the network:

```bash
docker run --rm -it \
  --cpuset-cpus="2,3" \
  -v "$(pwd)/results:/work/regressor/noise-bench/results" \
  --network none \
  regex-noise-bench
```

---

## 3. Bare-Metal Linux CPU Isolation

To control timing variance on a dedicated Linux host, isolate cores from the OS scheduler rather than relying on `taskset` alone:

1. **Isolate cores in GRUB** (`/etc/default/grub`), then update GRUB and reboot:
   ```text
   isolcpus=2,3 nohz_full=2,3 rcu_nocbs=2,3
   ```
   Verify after reboot:
   ```bash
   cat /proc/cmdline | grep isolcpus
   ```

2. **Pin CPU frequency and disable turbo boost**:
   ```bash
   sudo apt install linux-tools-common linux-tools-$(uname -r)
   sudo cpupower frequency-set -g performance
   sudo cpupower frequency-set -d 3.0GHz -u 3.0GHz  # match your CPU's base clock
   echo 1 | sudo tee /sys/devices/system/cpu/intel_pstate/no_turbo   # Intel
   # AMD equivalent: echo 0 | sudo tee /sys/devices/system/cpu/cpufreq/boost
   ```

3. **Disable the hyperthreading sibling** of your benchmark core:
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

```bash
export REGEX_REPO=/work/regressor/regex
export NOISE_BENCH_DIR=/work/regressor/noise-bench
cd "$NOISE_BENCH_DIR"
python3 harness/run_commit.py <sha> --reps 20 --iters 2000 --warmup 200
# Or run the full commit list in harness/commits.txt:
./run_batch.sh 1 999
python3 analyze/run_batch_analysis.py
```

If you collected raw commit directories in `noise-bench/results/commits/`, you can import them into SQLite instead of `data/regex_history.json.gz`:

```bash
python regressor.py import-legacy
python regressor.py batch regex
python regressor.py analyze regex 16d47c5 0a446ec
```

---

## 5. Software Capabilities & PMU Telemetry

### What Runs Anywhere vs. Bare-Metal Linux

| Capability | Standard Laptop / CI Runner | Dedicated Bare-Metal Linux (`isolcpus`) |
|---|---|---|
| Statistical engine, SQLite DB, Web UI, `PyMicroAdapter`, tests | Full support | Full support |
| Interleaved A/B (`compare-interleaved`), canary drift check, `bisect` | Full support | Full support (tighter MDE) |
| Native Rust historical builds (`RegexAdapter`) | Docker or local Rust toolchain | Native with pinned frequency & isolated cores |
| Hardware retired instructions (`PERF_COUNT_HW_INSTRUCTIONS`) | `pmu_status: "UNAVAILABLE"` | Available via `perf_event_open` |

### How PMU & Timing Telemetry Work

1. **Linux `perf_event_open` (`PERF_COUNT_HW_INSTRUCTIONS`)**: Counts retired instructions directly via hardware PMU MSRs (`IA32_FIXED_CTR0`), independent of CPU clock frequency or thermal throttling. In the unprivileged Study 1 VM, hardware PMU counters returned `<not supported>`, so `0a446ec` was triaged with software `cpu-clock` sampling flamegraphs (`+0.3%` CPU sample delta).
2. **User-space x86 `_rdtsc`**: Reads the invariant Time Stamp Counter across platforms without root privileges (used alongside wall-clock timings during local `8f5d947` ablation verification).
3. **Cloud VMs without vPMU (`pmu_status: "UNAVAILABLE"`)**: Standard cloud VMs and Windows hosts cannot read hardware PMU MSRs. `regressor` never fabricates counters: it records `pmu_status: "UNAVAILABLE"` and relies on $3\times\text{CV}$ noise-floor gating, interleaved A/B execution, and canary drift correlation.
