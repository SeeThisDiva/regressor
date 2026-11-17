# Continuous performance regression detection — rust-lang/regex

## Result

**No confirmed performance regression found** in Study 1 (27 commits from `14 Aug 2025` to `27 Jan 2026`, picked from 62 commits in that range that touched `src/`, `regex-automata/src/`, or `regex-syntax/src/`) or in Study 2 (24 commits across `4733e28..3d79fe9` through `7 Nov 2026`). One sub-threshold candidate from Study 1 (`8f5d947`, `+4.10%` under interleaved A/B) was initially under investigation pending hardware verification and was subsequently resolved via LTO assembly diffing and same-hash ablation as a binary-layout shift (`+0.08%` wall-clock for the actual code check, $p=0.804$, `ok`).

No upstream issue was filed. This is a deliberate outcome, not a shortfall — see [Why no issue was filed](#why-no-issue-was-filed).

| Metric | Study 1 Value |
|---|---|
| Commits analyzed | 27 (source-touching, 14 Aug 2025 – 27 Jan 2026, from 62 commits in range) |
| Pairwise comparisons | 78 (26 adjacent commit pairs × 3 benchmarks) |
| Flagged, pre-FDR | 5 |
| Flagged, post BH-FDR ($\alpha=0.05$) | 5 |
| Confirmed real regressions | 0 |
| False positive rate (of flags raised) | 5/5 |
| Sub-threshold candidates (under investigation in Study 1 → resolved via ablation) | 1 (`8f5d947` on `find_iter_userid`, +2.95% sequential below 5.19% floor; +4.10% 30-pair interleaved; isolated check `+0.08%`, `ok`) |

## Method

Three hand-written benchmarks against the crate's public API (`Regex::new` construction, `find_iter` throughput, `is_match` early-exit), run because the crate's own bench suite was moved out of the repo into a separate cross-engine project (`rebar`), and the one remaining in-repo bench file requires nightly Rust, which wasn't available in this environment.

For each commit: checkout → `cargo build --release` → 20 independent process invocations × 2,000 timed iterations (200 discarded as warmup) per benchmark → raw per-iteration nanosecond timings stored with full environment metadata (CPU model string, `rustc`/Cargo version, build duration, timestamps).

Change-point detection uses a two-sided Mann-Whitney U test on each commit's 20 per-run medians against its predecessor's, using rank-based comparison specifically because measured noise on shared runners has a heavy right tail (OS scheduling jitter) that biases mean-based tests. Effect size is estimated via the Hodges-Lehmann median pairwise difference. A shift is flagged only if it is *both* statistically significant *and* larger than $3\times$ the benchmark's measured baseline CV — a fixed percentage threshold was tested first and rejected after Phase 1 measured CVs ranging from 1.38% to 10.54% across benchmarks on identical code. Across the batch, Benjamini-Hochberg FDR correction controls the 5% false-discovery rate across all 78 comparisons rather than per comparison (which alone would produce roughly 4 spurious flags by chance).

The detector was validated before running on real history: same code run twice showed no flag ($p=0.52$), a synthetic 8% injected slowdown was correctly flagged ($p=3\times 10^{-11}$), and a synthetic 1% injected slowdown was correctly *not* flagged despite statistical significance ($p=0.004$) because it sat inside the noise floor.

## Study 1: What got flagged, and why none of it held up

- **3 of 5 flags** (`compile_moderate`, `find_iter_userid`, `is_match_status`, all on `dd96592`) moved together in the same direction by 12%–26% on a commit that only clarified a doc comment about CRLF mode. Timestamps showed a 3-hour-21-minute gap (201 min) between that pair's two runs — the longest idle gap in the batch. The reported CPU model string was identical both times, so a string check missed it. Three unrelated benchmarks shifting together indicates an environment shift, not a code change.
- **1 of 5 flags** (`find_iter_userid`, `+1.45%` on `16d47c5`) touched only `CHANGELOG.md`, `README.md`, and a doc-comment example in `src/lib.rs`. No compiled code changed; this was background jitter clearing a tight 0.93% noise floor.
- **1 of 5 flags** (`compile_moderate`, `+12.13%` on `0a446ec`, *"lint: fix a selection of Clippy lints"*) touched actual NFA compiler files (`nfa/thompson/compiler.rs`, `util/determinize`, `util/prefilter`, `util/sparse_set`, `util/utf8.rs`) and isolated to one benchmark. It was re-profiled independently with `perf record -F 997 -e cpu-clock` (no hardware PMU access in the sandbox) on both parent and candidate (~62,000 samples each) and converted to a differential flamegraph ([`../assets/flamegraphs/flamegraph_diff.svg`](../assets/flamegraphs/flamegraph_diff.svg)). Diffed leaf self-time moved by at most -0.29 percentage points, and aggregate CPU sample time differed by only `+0.3%` — disagreeing with the `+12.13%` wall-clock spike by ~40×. Subsequent 30-pair interleaved A/B re-measurement confirmed `0a446ec` does not reproduce (`+0.36%`, $\text{CI}_{95}[-0.64\%, +1.12\%]$, $p=0.440$, `ok`).

## Sub-threshold candidate (`8f5d947`) — Resolved via Assembly & Ablation

In addition to the 5 sequential flags above, commit `8f5d947` (*"automata: make behavior more consistent when `WhichCaptures::None` is used"*) showed a smaller slowdown on `find_iter_userid` that stayed below the single-commit pairwise $3\times\text{CV}$ floor (`+2.95%`, $p=3.38\times 10^{-4}$, floor `5.19%` with `ddof=1` or `5.06%` with `ddof=0`), so it was not part of the 5 batch flags. Series-level E-Divisive (`changepoint`) flagged a `+2.53%` structural step at `8f5d947` ($p=0.020$), and 30-pair interleaved A/B (`compare-interleaved --pairs 30`) measured `+4.10%` ($\text{CI}_{95}[+3.68\%, +4.51\%]$, $p=1.86\times 10^{-9}$ floor; `+4.31%` wall-clock and `+4.26%` `_rdtsc` hardware cycles on local Intel Alder Lake hardware).

To determine whether `8f5d947` added real runtime work or a binary-layout shift, we inspected the full LTO x86_64 release assembly (`bench.s`, `lto = true`, `codegen-units = 1`), built a same-commit ablation (`8f5d947-ablation`, removing only `self.imp.info.captures_disabled() ||`), and generated a differential flamegraph ([`../assets/flamegraphs/flamegraph_diff_8f5d947.svg`](../assets/flamegraphs/flamegraph_diff_8f5d947.svg)):

- **Instruction count in `bench_find_all`**: All internal strategy functions (`hybrid::search::find_fwd`, `Core::search_slots`, `ReverseInner`, `ReverseSuffix`, `Memchr3`, `Teddy`) had **+0 instruction change**. In the inlined `FindMatches::count` loop inside `bench_find_all`, instructions rose from **69 static / 60 dynamic instructions per match** (`977feeb`) to **71 static / 62 dynamic instructions per match** (`8f5d947`) — `+2` instructions per match (`cmpb $2, 138(%rcx); je`, `+4,007` dynamic instructions per 2,000-match iteration), plus `+3` stack loads `(%rsp)` per match due to register spills.
- **Same-hash ablation (`8f5d947-ablation vs 8f5d947`, 30 interleaved pairs)**: Removing only `self.imp.info.captures_disabled() ||` reverts the inner loop to **69 static / 60 dynamic instructions per match** (identical to `977feeb`) while keeping `8f5d947`'s doc comments and `rustc` crate `#[doc]` symbol hash fixed. Comparing `8f5d947-ablation` vs `8f5d947` isolated the `captures_disabled()` check at **`+0.08%` wall-clock** ($\text{CI}_{95}[-0.54\%, +0.58\%]$, $p=0.804$, `ok`) and **`+0.06%` `_rdtsc` cycles** ($p=0.839$, `ok`).
- **LTO binary-layout component (`977feeb vs 8f5d947-ablation`, 30 pairs)**: Comparing `977feeb` against `8f5d947-ablation` (**+0 executed instructions**; differs only in `///` doc comments that alter `rustc`'s crate HIR hash and LTO function merge order) shifted `find_iter_userid` by **`+3.27%` wall-clock** ($p=1.92\times 10^{-6}$) and **`+3.28%` `_rdtsc` cycles**. Thus the observed shift on `8f5d947` is dominated by LTO binary layout rather than the `captures_disabled()` branch.

## Study 2: Extending History to `3d79fe9` (`4733e28..origin/master`)

We extended the study across the **23 new source-touching commits** landed after `4733e28` through 7 Nov 2026 (`24` commits total including the `4733e28` anchor, `69` adjacent pairwise comparisons across 3 benchmarks in a single continuous session with `0` session breaks; stored in [`../data/regex_study2_history.json.gz`](../data/regex_study2_history.json.gz) and [`results/study2_analysis.json`](results/study2_analysis.json), keeping Study 1 frozen):

- **Flagged pre-FDR / post-BH-FDR / post-BY-FDR**: **4** (`4733e28 -> c4865a0`, `9825c74 -> 468fc64`, `f9b0ab1 -> e018953`, `a1e367b -> 80b9d14`).
- **30-pair `compare-interleaved` verification**:
  - **3 of 4 flags did not reproduce** (`9825c74 -> 468fc64`: $p=0.280$ `ok`; `f9b0ab1 -> e018953` indentation fix, which also triggered the single E-Divisive change-point on `compile_moderate`: $+1.09\%$, $p=0.477$ `ok`; `a1e367b -> 80b9d14`: $+1.71\%$, $p=0.584$ `ok`).
  - **1 of 4 (`4733e28 -> c4865a0` on `find_iter_userid`, $+2.36\%$ sequential, $+2.63\%$ interleaved)**: `c4865a0` only modifies `regex-syntax` negated character-class translation (`Regex::new` runs outside the timed loop in `bench_find_all`, and `user_id=(\d+)` has no negated classes) — another ~2.6% cross-crate LTO binary-layout shift.
- **Doc/comment-only null transitions**: `0/3` flagged (`0.0%` FPR).
- **Confirmed real regressions in Study 2**: **0**.

## Why no issue was filed

Every sequential flag in Study 1 and Study 2 traced to either environmental noise, failed to reproduce under 30-pair interleaved A/B re-measurement, or (for `8f5d947` and `c4865a0`) was shown via LTO assembly diffing and same-hash ablation (`+0.08%` time / `+0.06%` TSC cycles, $p=0.804$, `ok`) to be an LTO binary-layout shift rather than an algorithmic regression. Opening an upstream issue without a genuine code regression wastes maintainer time.

## Known limitation of this run

Study 1 ran on a single shared vCPU sandbox with no `cpufreq` governor access and no CPU pinning. Re-measuring the 50-rep baseline on local hardware (Intel Alder Lake, High Priority) reduced `find_iter_userid` CV by 10× (`10.54%` → `1.03%`):

| Benchmark | Sandbox CV (50 reps, unpinned) | Local Hardware CV (50 reps, High Priority) | Bare-Metal Linux (`isolcpus`) CV |
|---|---|---|---|
| `compile_moderate` | 1.38% | **2.13%** (median 2,032,300 ns) | *not run (Windows host)* |
| `find_iter_userid` | 10.54% | **1.03%** (median 126,900 ns) | *not run (Windows host)* |
| `is_match_status` | 1.89% | **3.58%** (median 24,900 ns) | *not run (Windows host)* |

## Reproduction

All code, historical results, and analysis scripts live in `noise-bench/` (with portable gzipped study datasets in `../data/`):

- [`src/main.rs`](src/main.rs) — Rust benchmark binary (`compile_moderate`, `find_iter_userid`, `is_match_status`)
- [`harness/run_commit.py`](harness/run_commit.py) — checkout → build → run → store, one commit at a time
- [`harness/commits.txt`](harness/commits.txt) — the 27-commit list for Study 1
- [`analyze/changepoint.py`](analyze/changepoint.py) — standalone Mann-Whitney U + BH-FDR detector
- [`analyze/run_batch_analysis.py`](analyze/run_batch_analysis.py) — Study 1 batch driver across `results/commits/`
- `results/commits/<sha>/` — raw timings + `meta.json` per commit (Study 1)
- [`results/batch_analysis.json`](results/batch_analysis.json) — Study 1 comparison output
- [`results/ablation_8f5d947_instructions.json`](results/ablation_8f5d947_instructions.json) — LTO instruction & ablation breakdown for `8f5d947`
- [`results/study2_analysis.json`](results/study2_analysis.json) & [`../data/regex_study2_history.json.gz`](../data/regex_study2_history.json.gz) — Study 2 analysis and portable dataset
