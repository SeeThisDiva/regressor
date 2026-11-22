# Study 3 Execution Plan: 1-Year Full-Commit Sweep (`rust-lang/regex`)

## 1. Commit Window & Inclusion Decision

- **Target window**: `2025-11-07` through `3d79fe9` (2026-11-07) on `rust-lang/regex` `master` (`5ea3eb1..3d79fe9`, i.e., `4733e28^..3d79fe9`).
  - Note: `5ea3eb1` (`1.12.2`, 2025-10-13) was `master` HEAD on `2025-11-07`; `4733e28` is the first commit landed after `2025-11-07` and is the shared anchor commit from Study 1 and Study 2.
  - Note: `git -C regex fetch` on `2026-11-18` also fetched 16 newer post-window commits (`3d79fe9..4226f21`, dated `2026-11-18`). Study 3 strictly targets the 1-year window ending at `3d79fe9`.
- **Total commits in window**: **51 commits** (linear history, 0 merge commits).
  - **24 commits** touching `src/`, `regex-automata/src/`, or `regex-syntax/src/`.
  - **1 commit** touching `regex-lite/src/` only (`a7f2ff6`, documentation clarification).
  - **26 commits** touching only non-source files (`Cargo.toml` version/packaging bumps, `CHANGELOG.md`, `AI_POLICY.md`, `.github/FUNDING.yml`, `.ignore`, `testdata/regression.toml`, integration `tests/`).
  - **29 null-control commits** total (26 non-source + 2 doc-comment-only in `src/`/`regex-automata/src/` [`2c7b172`, `c420333`] + 1 doc-comment-only in `regex-lite/src/` [`a7f2ff6`]), plus 2 whitespace/formatting-only commits (`e018953`, `30390ec`).
- **Decision: Run EVERY commit (all 51)** rather than filtering to the 24 source-touching commits:
  1. Satisfies the continuous profiling requirement ("profile every commit").
  2. Doc-only, changelog, and `Cargo.toml` metadata commits provide 29 natural **null-transition controls** (`core/power.py` Tier 3 empirical FPR calibration) and expose cross-crate `rustc` LTO layout sensitivity to non-code metadata (`#[doc]` / crate version hashes).
  3. Commits are executed in strict `git log --reverse` topological order (not sorted by `author_date`, which is non-monotonic on rebased PRs).

## 2. Host Pinning & Isolation (Windows 11 / Intel i7-12650H)

- **CPU topology** (queried via `GetLogicalProcessorInformationEx`):
  - Physical cores 0–5 (`EfficiencyClass=1`, P-cores): HT pairs `[0,1]`, `[2,3]`, `[4,5]`, `[6,7]`, `[8,9]`, `[10,11]`.
  - Physical cores 6–9 (`EfficiencyClass=0`, E-cores): `[12]`, `[13]`, `[14]`, `[15]`.
- **Execution pinning**:
  - During `cargo build --release` (in an isolated `git worktree` placed in `%TEMP%\regressor-study3-builds` outside OneDrive sync), full multi-core affinity is preserved so LTO builds complete rapidly without OneDrive IO interference.
  - During canary sampling and `noise-bench` timing runs, the driver pins itself and spawns `noise-bench.exe` with:
    - Fixed single-P-core CPU affinity (defaulting to the second P-core logical CPU, e.g., CPU `2` or `4`, avoiding Core 0 OS interrupt pressure and leaving the HT sibling idle).
    - `HIGH_PRIORITY_CLASS` (`creationflags=subprocess.HIGH_PRIORITY_CLASS` on Windows, verified necessary because `CreateProcess` resets child priority to `NORMAL_PRIORITY_CLASS` unless explicitly flagged).
- **Host drift canary**:
  - `CanaryBenchmark.run_reps(reps=15, iters=8000, warmup=2)` runs on the same pinned P-core immediately **before** and **after** every commit's benchmark sweep.
  - Both within-commit drift (`canary_before` vs `canary_after`) and cross-commit drift (`prev_canary_after` vs `canary_before`) are logged to `noise-bench/logs/study3_canary.jsonl` and each commit's `meta.json`.

## 3. Sample Size (`N`) & Benjamini-Yekutieli FDR Time-Budget Model

With ~25 benchmarks across 50 adjacent transitions (`m ≈ 1,250` hypotheses) under `batch regex --fdr by`:
- Harmonic sum $H(1250) \approx 7.708$.
- Benjamini-Yekutieli rank-1 cutoff at $Q = 0.05$:
  $$p_{(1)} \le \frac{0.05}{1250 \times 7.708} \approx 5.19 \times 10^{-6}.$$
- Minimum achievable exact two-sided Mann-Whitney U p-value for $N$ reps per commit is $p_{\min}(N) = 2 / \binom{2N}{N}$:
  - $N = 10$: $p_{\min}(10) = 1.08 \times 10^{-5} > 5.19 \times 10^{-6}$ (**cannot pass BY-FDR** even with zero overlap!).
  - $N = 15$: $p_{\min}(15) = 1.29 \times 10^{-8} \ll 5.19 \times 10^{-6}$ (81% power at $+5\%$ shift on baseline MDE table).
  - $N = 20$: $p_{\min}(20) = 1.45 \times 10^{-11} \ll 5.19 \times 10^{-6}$ (86% power at $+5\%$ shift; matches Studies 1 & 2).
- **Choice of `N` (calibrated via 2-commit smoke run on `4733e28` & `3d79fe9`)**:
  - Smoke run config: `iters=1000, warmup=100` (with `compile_moderate` at `iters=400, warmup=50` via `study3_iters.json`, matching Study 2), pinned to P-core logical CPU `2` (`EfficiencyClass=1`) at `HIGH_PRIORITY_CLASS` (`128`).
  - Measured smoke timings (5 reps × 25 benchmarks):
    - Isolated build: `53.8s` (`4733e28`) and `51.3s` (`3d79fe9`), mean `t_build ≈ 52.5s/commit`.
    - Benchmark suite: `40.4s` (`4733e28`) and `41.3s` (`3d79fe9`), mean **`t_suite ≈ 8.17s/rep`** across all 25 benchmarks (pinned CVs mostly `0.05%–0.92%`, `compile_moderate` `0.91%–1.50%` vs `7.27%` unpinned).
  - Projected wall times across all 51 commits:
    - `N = 15`: `51 × (52.5 + 15 × 8.17 + ~1.5 canary) ≈ 51 × 176.6s ≈ 150 min (~2.5 hours)` (+ ~8 min for 50-rep `3d79fe9` baseline session).
    - `N = 20`: `51 × (52.5 + 20 × 8.17 + ~1.5 canary) ≈ 51 × 217.4s ≈ 185 min (~3.1 hours)`.
  - **Selected `N = 15` reps/commit**: fits comfortably in a ~2.5-hour window, achieves the same `+5%` MDE@80% power tier as `N = 20` (`PROJECT_EXPLANATION.md` §8), and yields `p_min(15) = 1.29 × 10^-8` (400× below the `m ≈ 1,250` Benjamini-Yekutieli rank-1 threshold `5.19 × 10^-6`).

## 4. Crash-Safety & Resumability

- A commit is the atomic measurement unit: interrupting mid-commit leaves its status `"in_progress"`, and resuming cleans up the stale worktree and re-runs that commit cleanly in one uninterrupted session (preventing intra-commit thermal/session splits).
- Every completed commit persists:
  1. Compressed raw per-iteration samples in `noise-bench/results/study3_commits/<short10>/<bench>.samples.json.gz`.
  2. SQLite rows via `core.db.Database` (`insert_commit` + `insert_runs_bulk`, idempotent upserts).
  3. Atomic `meta.json` (`status: "complete"`) written via temp file + `os.replace`.
  4. Append-only `fsync`-flushed logs (`noise-bench/logs/study3_progress.jsonl`, `noise-bench/logs/study3_canary.jsonl`) and atomic `noise-bench/results/study3/checkpoint.json`.
