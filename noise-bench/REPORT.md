# Continuous performance regression detection — rust-lang/regex

## Result

**No confirmed performance regression found** in the 27 commits from the last
12 months that touched `src/`, `regex-automata/src`, or `regex-syntax/src`.
No upstream issue was filed. This is a deliberate outcome, not a shortfall —
see "Why no issue was filed" below.

| Metric | Value |
|---|---|
| Commits analyzed | 27 (source-touching, last 12 months) |
| Pairwise comparisons | 78 (26 adjacent commit pairs × 3 benchmarks) |
| Flagged, pre-FDR | 5 |
| Flagged, post BH-FDR (α=0.05) | 5 |
| Confirmed real regressions | 0 |
| False positive rate (of flags raised) | 5/5 |

## Method

Three hand-written benchmarks against the crate's public API (`Regex::new`
construction, `find_iter` throughput, `is_match` early-exit), run because
the crate's own bench suite was moved out of the repo into a separate
cross-engine project (`rebar`), and the one remaining in-repo bench file
requires nightly Rust, which wasn't available in this environment.

For each commit: checkout → `cargo build --release` → 20 independent process
invocations × 2000 timed iterations (200 discarded as warmup) per benchmark →
raw per-iteration nanosecond timings stored with full environment metadata
(CPU model string, rustc/cargo version, build duration, timestamps).

Change-point detection: Mann-Whitney U test on each commit's 20 per-run
medians against its predecessor's, using rank-based comparison specifically
because measured noise on this platform has a heavy right tail (OS
scheduling jitter) that would bias a mean-based test. Effect size via the
Hodges-Lehmann estimator. A shift is only flagged if it is *both*
statistically significant *and* larger than 3× the benchmark's own measured
noise floor — a fixed percentage threshold was tested first and rejected
after phase 1 measured coefficient-of-variation ranging from 1.4% to over
10% across benchmarks on identical code, meaning one global cutoff is either
too loose or drowns in false positives depending which benchmark it's
applied to. Across the batch, Benjamini-Hochberg FDR correction was applied
so the 5% false-discovery rate is controlled over all 78 comparisons rather
than per-comparison, which alone would produce roughly 4 spurious flags by
chance.

The detector was validated before being trusted on real history: same code
run twice showed no flag (p=0.52), a synthetic 8% injected slowdown was
correctly flagged (p=3e-11), and a synthetic 1% injected slowdown was
correctly *not* flagged despite being technically significant (p=0.004) —
because it sat inside the noise floor. That last case is the actual answer
to "why not a fixed threshold": statistical significance and practical
significance are different questions.

## What got flagged, and why none of it held up

**3 of 5 flags** (`compile_moderate`, `find_iter_userid`, `is_match_status`,
all on the same commit pair) moved together, in the same direction, by
12–26%, on a commit that only clarified a doc comment about CRLF mode.
Timestamps showed a 3-hour-21-minute gap between that pair's two runs — the
longest idle gap in the whole batch. Same reported CPU model string both
times, so the host-identity check built into the harness didn't catch it;
whatever changed was some other property of the shared, unpinned sandbox.
Three unrelated benchmarks shifting together is the signature of an
environment change, not a code change.

**1 of 5 flags** (`find_iter_userid`, +1.45%) was on a commit whose diff
touches only `CHANGELOG.md`, `README.md`, and a doc-comment example in
`src/lib.rs`. No compiled code changed. A pure-documentation commit cannot
cause a real runtime shift; this was noise that happened to clear both
thresholds.

**1 of 5 flags** (`compile_moderate`, +12.13%, "lint: fix a selection of
Clippy lints") was the one candidate worth real scrutiny — it touched actual
hot-path files in the NFA compiler (`nfa/thompson/compiler.rs`,
`util/determinize`, `util/prefilter`, `util/sparse_set`, `util/utf8.rs`),
and the flag was isolated to one benchmark rather than spread across all
three, which is structurally what a real, narrow code effect should look
like. It was profiled independently with `perf` (software `cpu-clock`
events; no hardware PMU access in this sandbox) on both the commit and its
parent, ~62,000 samples each, converted to flamegraphs. Diffed self-time by
leaf function: the largest mover anywhere in the call graph was -0.29
percentage points, and it went *down*. Aggregate weighted CPU time was +0.3%
in the candidate — nowhere near the +12% the wall-clock harness reported.
Two independent measurement methods disagreeing by roughly 40x means the
original signal doesn't reproduce, not that the regression is subtle.

## Why no issue was filed

Every flag traced to either environmental noise (confirmed via timestamp
correlation) or failed to reproduce under a second, independent measurement
(confirmed via flamegraph profiling). There is no reproduction to hand to
the regex maintainers, and opening an issue anyway — "here's something my
detector flagged, I couldn't confirm it, might be worth a look" — is the
complaint-not-reproduction pattern that wastes a maintainer's time rather
than respecting it.

## Known limitation of this run

This entire pipeline ran on a single shared vCPU sandbox with no `cpufreq`
governor access and no CPU pinning. The 3h21m-gap incident and the
flamegraph/wall-clock disagreement both point the same direction: this
specific environment isn't stable enough to fully trust close calls, even
with 20 reps and a validated statistical test. The pipeline itself — harness,
statistics, FDR correction, and the triage workflow — held up under
scrutiny; a from-scratch run on pinned, dedicated hardware is the natural
next step before treating any future flag as actionable without this same
level of manual double-checking.

## Reproduction

All code, raw per-commit results, and the analysis scripts are in
`noise-bench/`:
- `src/main.rs` — benchmark binary
- `harness/run_commit.py` — checkout → build → run → store, one commit at a time
- `harness/commits.txt` — the 27-commit list this run covers
- `analyze/changepoint.py` — the validated detector (`compare()`, `bh_fdr_correct()`)
- `analyze/run_batch_analysis.py` — batch driver, adjacent-pair comparison across the full set
- `results/commits/<sha>/` — raw timings + `meta.json` per commit
- `results/batch_analysis.json` — full comparison output before/after FDR
