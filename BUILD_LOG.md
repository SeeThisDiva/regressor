# Build Log: Bugs That Cost Hours

A technical log of the hardest bugs encountered while building `regressor`, recorded as: **symptom → what we thought it was → what it actually was → the fix and regression test**.

---

## 1. The Pooled-Iterations Fallacy in Mann-Whitney U

- **Where**: [`noise-bench/analyze/changepoint.py`](noise-bench/analyze/changepoint.py) (`load_samples` vs. `load_rep_summaries`), [`core/detector.py`](core/detector.py) (`compare_distributions`)
- **Symptom**: Tiny, meaningless timing differences (~0.05%–0.5%) on noisy runs produced astronomical statistical significance ($p < 10^{-20}$).
- **What we thought it was**: Pooling all 2,000 inner iterations across 20 runs into two $N = 40{,}000$ arrays gives Mann-Whitney U maximum statistical power.
- **What it actually was**: Inner iterations inside one process invocation share ASLR memory layout, branch predictor state, allocator state, and L1/L2 cache lines—they are **not independent**. Feeding $N = 40{,}000$ correlated observations into a test that assumes i.i.d. samples treats each iteration as an independent draw, inflating sample size by 2,000× and turning process-level jitter into false $p < 10^{-20}$ detections.
- **Fix & verification**: Aggregate each independent process invocation to a single summary median first (`load_rep_summaries`), and run Mann-Whitney U and Hodges-Lehmann strictly across the $N = 20$ independent process medians.

---

## 2. E-Divisive Permutation Bias: 37.3% False Positives at Nominal 5%

- **Where**: [`core/series_detector.py`](core/series_detector.py) (`_split_stats`, `detect_series_changepoints_edivisive`), [`tests/test_stage1_stats.py`](tests/test_stage1_stats.py) (`test_edivisive_false_positive_rate_on_pure_noise`)
- **Symptom**: Running series-level E-Divisive change-point detection on pure i.i.d. Gaussian noise at nominal $\alpha = 0.05$ flagged a change point in **37.3%** of trials instead of ~5%.
- **What we thought it was**: Maybe the energy-distance formula had a scaling bug, or 27 commits was simply too short for permutation testing.
- **What it actually was**: In each segment, the candidate split $\tau^*$ was chosen by **maximizing** the weighted energy statistic over all admissible splits. The permutation test then shuffled the series and evaluated the permuted statistic only at that fixed $\tau^*$. Comparing $\max_\tau S(\tau)$ against $S_{\text{perm}}(\tau^*)$ at a single fixed index ignores the selection search over splits and severely understates the null tail.
- **Fix & verification**: For every permutation, compute the **maximum over all admissible splits** $\max_\tau S_{\text{perm}}(\tau)$. To make that fast instead of $O(n^3)$, `_split_stats` computes a 2-D cumulative sum over the $n \times n$ pairwise distance matrix $|x_i - x_j|$ so all splits together cost $O(n^2)$. Empirical FPR on pure noise dropped from **37.3% to 4.3%**, guarded by [`tests/test_stage1_stats.py`](tests/test_stage1_stats.py).

---

## 3. Invariant Canary Blinded to ~22% Drift by One Cold-Start Sample

- **Where**: [`core/canary.py`](core/canary.py) (`CanaryBenchmark.run_reps`, `CanaryBenchmark.evaluate_drift`), [`tests/test_stage1_stats.py`](tests/test_stage1_stats.py) (`test_canary_cold_start_outlier_does_not_blind_the_check`, `test_canary_max_allowed_noise_cap_catches_10pct_shift`)
- **Symptom**: During a real ~22% host drift event in `compare-interleaved`, the invariant SHA-256 canary reported `OK` instead of `ENVIRONMENT_SUSPECT`.
- **What we thought it was**: The canary threshold multiplier ($2\times \text{CV}$) was too loose, or the SHA-256 loop was too short to reflect host load.
- **What it actually was**: The very first canary sample after subprocess benchmark activity is reliably 30–45% slower due to cold caches and CPU frequency ramp (e.g., `4970.0` ns vs. `~3400` ns). Because the original spread check used standard deviation (`np.std`) with zero warmup samples discarded, that single cold-start outlier inflated the CV and widened the allowed-noise band to roughly $\pm 27\%$, blinding the canary to a 22% shift.
- **Fix & verification**: Discard `warmup=2` initial samples in `CanaryBenchmark.run_reps`, replace standard deviation with robust MAD-based spread ($1.4826 \times \text{MAD} / \text{median}$), and bound the allowed-noise band with `min_drift_pct=2.5%` and `max_allowed_noise_pct=5.0%`. Verified in [`tests/test_stage1_stats.py`](tests/test_stage1_stats.py).

---

## 4. Timer Quantization on `is_match_status` (~50 ns) and Sub-100 ns Synthetic Injections

- **Where**: [`noise-bench/src/main.rs`](noise-bench/src/main.rs) (`IS_MATCH_BATCH`, `busy_wait_ns`), [`adapters/pymicro_adapter.py`](adapters/pymicro_adapter.py), [`tests/test_stage4_hardening_and_handoff.py`](tests/test_stage4_hardening_and_handoff.py)
- **Symptom**: `is_match_status` timings clustered at quantized timer steps with huge apparent variance, and a synthetic ~1% injection in `PyMicroAdapter` jumped in discrete ~5× steps instead of scaling smoothly. Also, synthetic injections were too clean compared to real regressions.
- **What we thought it was**: Host scheduling jitter on Windows/Linux VMs was swamping microsecond-scale measurements.
- **What it actually was**: Three related measurement bugs:
  1. `is_match` on the test haystack short-circuits in ~50 ns—at or below `Instant::now()` resolution and call overhead, so we were timing the clock call rather than regex execution.
  2. In `PyMicroAdapter`, a 1% (~30 ns) busy-wait quantized to 100 ns Windows timer ticks and `perf_counter_ns()` overhead.
  3. An earlier version of `noise-bench` added `inject_ns` to `start.elapsed().as_nanos()` *after* timing ended instead of executing real CPU busy-wait inside the timed window.
- **Fix & verification**: Batch `IS_MATCH_BATCH = 500` calls per timed sample in [`noise-bench/src/main.rs`](noise-bench/src/main.rs), batch 8 ops per timed sample in [`adapters/pymicro_adapter.py`](adapters/pymicro_adapter.py), and spin `busy_wait_ns(inject_ns)` inside the timed block so injected delays undergo real OS/CPU noise. Guarded by `test_rust_harness_injects_inside_timed_region_and_renames_tsc_ticks` in [`tests/test_stage4_hardening_and_handoff.py`](tests/test_stage4_hardening_and_handoff.py).

---

## 5. Quiet-Host Inversion in the 1% Synthetic Validation Gate

- **Where**: [`core/validation.py`](core/validation.py) (`validate_adapter_synthetic`), [`tests/test_validation_gate.py`](tests/test_validation_gate.py)
- **Symptom**: Running `validate-adapter` on a low-noise host failed the 3-point synthetic injection check even though the adapter and detector were working properly.
- **What we thought it was**: An adapter bug amplifying `inject_ns`.
- **What it actually was**: The 1% injection gate originally asserted `verdict == "ok"` (expecting the 1% shift to sit inside the $3\times \text{CV}$ noise floor). On a quiet host whose measured floor was $< 1\%$, a genuine 1% busy-wait slowdown *should* be detected—meaning the sanity check failed precisely when the machine was cleanest.
- **Fix & verification**: Pass the 1% gate when either `verdict == "ok"` OR (`noise_floor_pct < small_target_pct` and `|shift_pct| <= 3.0 * small_target_pct`), so quiet hosts pass while broken adapters that ignore or wildly amplify `inject_ns` (e.g., 5×) still fail. Guarded by [`tests/test_validation_gate.py`](tests/test_validation_gate.py).

---

## 6. Other Notable Fixes

- **Optional stopping in borderline bisect re-probing** ([`core/bisect.py`](core/bisect.py), [`tests/test_review_fixes.py`](tests/test_review_fixes.py)): Pooling batch 1 and batch 2 after peeking at a borderline probe violates nominal $\alpha$ calibration; fixed by deciding strictly on the fresh confirmation batch while keeping the pooled estimate informational only. Also replaced DB-backed bisection (which could "bisect" non-reproducing historical flags) with live interleaved build probing that halts immediately if `bad` does not regress against `good`.
- **`/series` N+1 DB queries and repeated schema init** ([`core/db.py`](core/db.py), [`server/app.py`](server/app.py), [`tests/test_stage2_data.py`](tests/test_stage2_data.py)): Loading runs per commit per benchmark and re-running `init_db()` on every API call caused 86 SQLite connections per `/series` request. Fixed via one bulk query (`get_project_runs`) and per-process `_INITIALIZED` tracking, reducing `/series` to 5 connections (guarded at $\le 8$).
- **SQL `LIKE` wildcard matching and non-idempotent imports** ([`core/db.py`](core/db.py), [`server/app.py`](server/app.py), [`tests/test_stage2_data.py`](tests/test_stage2_data.py)): `GET /api/commits/%%%%/distribution` previously matched arbitrary commits via `LIKE`; replaced with `substr()`. Added unique indexes (`uq_commits_project_sha`, `uq_runs_commit_bench_rep`) and `dedupe()` so re-importing never duplicates rows.
- **Hardcoded 106 µs baseline and non-interleaved validation** ([`noise-bench/collect_validation.sh`](noise-bench/collect_validation.sh), [`tests/test_stage4_hardening_and_handoff.py`](tests/test_stage4_hardening_and_handoff.py)): Replaced the hardcoded `106000` ns pilot assumption and sequential collection with a live 3-rep pilot median (`BASE_NS`) and 4-way rotating interleaving across `baseline_A`, `baseline_B`, `inject_8pct`, and `inject_1pct`.
- **Rust `#[doc]` crate-hash LTO layout shifts masquerading as code regressions (`8f5d947`)** ([`noise-bench/results/ablation_8f5d947_instructions.json`](noise-bench/results/ablation_8f5d947_instructions.json), [`assets/flamegraphs/flamegraph_diff_8f5d947.svg`](assets/flamegraphs/flamegraph_diff_8f5d947.svg)): Commit `8f5d947` shifted `find_iter_userid` by `+4.10%` (`+4.31%` wall-clock / `+4.26%` `_rdtsc` cycles locally) and added `+2` instructions per match (`cmpb $2, 138(%rcx); je`). Removing `self.imp.info.captures_disabled()` while keeping `8f5d947`'s doc comments fixed (`8f5d947-ablation`) showed `captures_disabled()` itself costs only `+0.08%` time / `+0.06%` TSC cycles ($p=0.804$, `ok`), while `977feeb -> 8f5d947-ablation` (`69 -> 69` inner-loop instructions, `+0` executed instructions) still shifted `+3.27%` because `rustc` hashes `#[doc = "..."]` attributes into the crate symbol disambiguator (`CsbJgdmo16x0m` -> `CsfJNDbjyD37i`), altering LTO function merge order and `.text` alignment.
