# Running this on your own hardware

The sandbox this was built in is a shared single-vCPU VM with no CPU pinning
and no governor control — that's the root cause behind every false positive
in `REPORT.md`. None of that is fixable in software; it needs real hardware
access. This doc is Linux-first because the noise-control levers (governor,
isolcpus, turbo disable) mostly don't exist as user-facing controls on macOS
or Windows. If you're on macOS/Windows, run this inside a Linux VM (UTM,
Docker Desktop's VM, or a cloud box) rather than trying to pin the host.

## 1. Get the code onto your machine

Unzip the package, you'll have:
```
noise-bench/       # the harness, benchmarks, analysis scripts, prior results
Dockerfile          # containerized build/run environment
```
You still need the target repo itself — don't ship a stranger's `.git`
history around, just clone fresh:
```bash
git clone https://github.com/rust-lang/regex.git
```

## 2. Containerize it (do this before building any historical commit)

```bash
docker build -t regex-noise-bench -f Dockerfile .
mkdir -p results
docker run --rm -it \
  --cpuset-cpus="2,3" \
  -v "$(pwd)/results:/work/noise-bench/results" \
  --network none \
  regex-noise-bench
```
`--network none` after the image is built means no further network access at
all during the actual commit-building/benchmarking phase — the image already
has the repo and crate registry cache baked in from the build step, so this
is the point where you get the strongest version of the original safety
requirement: zero network reachable while running a stranger's build scripts.
Drop `--network none` only if you need to `git fetch` newer commits first.

## 3. CPU isolation on the host (this is the part that actually controls noise)

**Pin cores away from the OS scheduler entirely**, don't just `taskset` a
process onto a core the kernel is still free to interrupt:

```bash
# Add to kernel boot params (GRUB), then reboot:
#   isolcpus=2,3 nohz_full=2,3 rcu_nocbs=2,3
# This tells the scheduler to never place other tasks on cores 2-3.
cat /proc/cmdline | grep isolcpus   # verify after reboot
```

**Fix the frequency, disable turbo:**
```bash
sudo apt install linux-tools-common linux-tools-$(uname -r)
sudo cpupower frequency-set -g performance   # not "powersave" or "ondemand"
sudo cpupower frequency-set -d 3.0GHz -u 3.0GHz  # pin min=max, pick your CPU's base clock
echo 1 | sudo tee /sys/devices/system/cpu/intel_pstate/no_turbo   # Intel
# AMD equivalent: echo 0 | sudo tee /sys/devices/system/cpu/cpufreq/boost
```

**Disable hyperthreading on the pinned cores** (a sibling thread waking up
mid-benchmark is a classic noise source):
```bash
echo 0 | sudo tee /sys/devices/system/cpu/cpu3/online   # if cpu3 is the HT sibling of cpu2
```

**Run the actual benchmark pinned to the isolated core:**
```bash
taskset -c 2 nice -n -20 ./target/release/noise-bench find_iter_userid 2000 200
```

**Sanity-check the noise floor before trusting anything downstream** —
literally repeat Phase 1:
```bash
NOISE_BENCH_DIR=/work/noise-bench python3 -c "..."   # or reuse collect_validation.sh
```
Compare the coefficient of variation against what's in `REPORT.md` (1.4% on
`compile_moderate`, 10.5% on `find_iter_userid` in the sandbox). If pinned
hardware doesn't get meaningfully below those numbers, something in the
pinning setup isn't taking effect — worth stopping and debugging before
running the full batch.

## 4. Run it

Everything downstream is unchanged — same scripts, same statistics:
```bash
export REGEX_REPO=/work/regex
export NOISE_BENCH_DIR=/work/noise-bench
python3 harness/run_commit.py <sha> --reps 20 --iters 2000 --warmup 200
# or the full batch:
./run_batch.sh 1 999   # start=1, count=999 (all of harness/commits.txt)
python3 analyze/run_batch_analysis.py
```

## 5. Scope: Software-Only vs. Bare-Metal Hardware Milestones

- **Current Pass (Software Architecture & Methodology)**:
  - Project-agnostic adapter decoupling (`BaseAdapter`, `RegexAdapter`, `PyMicroAdapter`).
  - SQLite persistence schema (`projects`, `commits`, `runs`, `comparisons`).
  - Non-parametric Mann-Whitney U on independent per-run medians + Hodges-Lehmann effect size + $3\times\text{CV}$ noise gating + Benjamini-Hochberg FDR control.
  - Invariant canary benchmark (`CanaryBenchmark`) detecting hypervisor/host drift without relying on CPU model strings.
  - Interactive laboratory-ledger frontend and REST API (`regressor serve`).
  - Synthetic ground-truth validation (3-point injection gate) enforcing sensitivity contracts before running real history.

- **Tracked Hardware Deployment Milestone**:
  - Provision bare-metal Linux host (e.g. AWS `c5.metal` or physical lab server).
  - Apply GRUB kernel boot flags (`isolcpus=2,3 nohz_full=2,3 rcu_nocbs=2,3`).
  - Lock governor (`performance`) and disable turbo boost (`no_turbo=1`).
  - Re-run `regressor validate-adapter` on bare-metal to calibrate tighter noise floors.

---

## 6. PMU Architecture: What the Counters Actually Do

Performance Monitoring Unit (PMU) metrics are frequently hand-waved in benchmark tooling. In `regressor`, the mechanics are unvarnished:

1. **Linux `perf_event_open` (`PERF_COUNT_HW_INSTRUCTIONS`)**:
   - Programmed via Linux syscall directly into hardware PMU MSRs (`IA32_FIXED_CTR0`).
   - Counts **retired instructions** with deterministic hardware precision.
   - Independent of CPU clock frequency, thermal throttling, and context switch stalls.
   - **Triage role**: When wall-clock latency shifts by +12% but retired instructions show $\Delta \le 0.1\%$, that is strong evidence the timing shift is not an algorithmic regression (it can still be a memory-layout or cache effect). (Note: In the unprivileged sandbox VM, hardware PMU counters returned `<not supported>`, so commit `0a446ec` was triaged using software `cpu-clock` sampling flamegraphs showing a $+0.3\%$ CPU delta; on bare-metal Linux, `perf stat -e instructions` provides hardware-counter precision).

2. **User-Space x86 `_rdtsc`**:
   - Assembly `rdtsc` instruction reads the invariant Time Stamp Counter.
   - Counts **nominal cycles** across platforms without requiring root or kernel capabilities.

3. **Cloud VMs without vPMU (`pmu_status: "UNAVAILABLE"`)**:
   - Standard cloud VMs (AWS EC2 non-metal, GitHub-hosted runners) do not virtualize PMU MSRs. Calling `perf_event_open` fails with `EACCES` or returns `<not supported>`.
   - `regressor` does NOT fabricate metrics: it sets `pmu_status: "UNAVAILABLE"` and safely falls back to noise-floor gating ($3\times\text{CV}$) and canary correlation.

---

## 7. Unified CLI Quickstart

```bash
# 1. Initialize SQLite database & register projects from projects/*.toml
python regressor.py init

# 2. Run mandatory 3-point synthetic validation & canary drift test
python regressor.py validate-adapter PyMicroAdapter
python regressor.py validate-adapter RegexAdapter

# 3. Import historical benchmark runs
python regressor.py import-legacy

# 4. Run batch change-point detection across commits
python regressor.py batch regex

# 5. Ad-hoc compare any two arbitrary commits
python regressor.py analyze regex 16d47c5 0a446ec

# 6. Launch live laboratory ledger UI
python regressor.py serve --port 8000
```
Visit `http://localhost:8000` to interact with the time-series ledger, commit drill-down modal, pairwise comparison tool, and differential flamegraphs.
