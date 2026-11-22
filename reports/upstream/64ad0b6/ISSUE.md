# Performance Regression (~95% / ~1.95x Slower) on `.*.*=.*` (`rebar` `cloud-flare-redos`) After `64ad0b6`

## Summary

Commit [`64ad0b6`](https://github.com/rust-lang/regex/commit/64ad0b618e043b791ed5385dd5504a436da1ddae) (`automata: fix bug in reverse suffix/inner optimization`, fixing `#1354`) introduced a persistent **+94.7% (~1.95x)** throughput regression on `rebar`'s `curated/06-cloud-flare-redos/simplified-long` workload (`r".*.*=.*"` on a 10,001-byte `x=xxxx...` haystack when consuming match spans via `Regex::find` / `Regex::find_iter(...).map(|m| m.len())`).

This report is shared respectfully in case this fallout on `rebar`'s `cloud-flare-redos` benchmark was unintended. We completely recognize that `#1354` prioritized leftmost-first match-span correctness and explicitly noted conservative fallbacks to `Core` for certain overlapping prefixes.

## Root Cause Analysis

Prior to `64ad0b6` (at parent `fa91c31`), `r".*.*=.*"` selected `Strategy::ReverseInner`:

1. `preinner` (`Memchr` scanning for `b'='`) locates `'='` at offset `1`.
2. A 1-byte reverse check confirms `.*.*` back to offset `0`.
3. `stopat::hybrid_try_search_half_fwd` runs a single forward scan across the haystack (`64.0 us` for 2 batched searches, or `~32.0 us` per search).

In `64ad0b6`, `ReverseInner::new` calls `reverse_inner::has_no_earlier_match(&prefilter.prefix, &prefilter.literals)`, which calls `prefix::hir_can_contain_literal(&concat_prefix, b"=")`. Because `concat_prefix` is `.*.*` and `.` can match `b'='`, `has_no_earlier_match` conservatively returns `false` and `Strategy::new` falls back to `Core`:

- Without the inner prefilter, `Core::search` executes **both** a full-haystack forward scan (`hybrid::search::find_fwd`) **and** a full-haystack reverse scan (`hybrid::search::find_rev`) to resolve the match start offset, nearly doubling wall time (`64,000 ns -> 124,600 ns`).
- *(Note on `Iterator::count`: `Regex::find_iter(...).count()` overrides `Iterator::count` via `Matches::count` -> `search_half` and skips `find_rev`, showing only a `+9.22%` forward-only shift. Any caller that reads match positions/slices via `find`, `find_iter`, or `captures` pays the full `+94.7%` cost.)*

Windows user-mode stack sampling (`assets/flamegraphs/flamegraph_diff_64ad0b6.svg`) directly observes this shift (`fa91c31` `2,225` samples / `3.412s` vs `64ad0b6` `4,330` samples / `6.863s`):

- **`fa91c31` (baseline)**: `2,168 / 2,225` samples (`97.44%`) in `ReverseInner::search -> stopat::hybrid_try_search_half_fwd`.
- **`64ad0b6` (candidate)**: `4,263 / 4,330` samples (`98.45%` inclusive) in `Core::search` (`4,261 / 4,330` or `98.41%` in `hybrid::regex::Regex::try_search`: `2,384` inclusive / `2,382` self samples = `55.06%` in `find_fwd` + `1,877` samples = `43.35%` in `find_rev`).

### Possible Mitigation Note

Because `.*.*` (at a top-level prefix without intervening restrictions and with a single literal `=`) matches any non-`\n` bytes greedily back to byte `0` (or the start of the line) from the first `=` found by `preinner`, no valid match on that line can start strictly earlier than the start found by reversing from that candidate. If a lightweight HIR check can recognize unconstrained greedy wildcard prefixes (or if such patterns remain intentionally routed through `Core` for simplicity), this note is meant simply as a data point from running `rebar` over the 1-year `regex` commit window.

## Benchmark Measurements

| Measurement | Baseline | Candidate | Median (Base -> Cand) | Shift (HL) | 95% CI | Wilcoxon / Perm p |
|---|---|---|---|---|---|---|
| Year-long Study 3 transition (`51` commits, `25` benches) | `fa91c31` | `64ad0b6` | `64,100.0 ns -> 124,600.0 ns` | `+94.38%` | — | `1.86e-07` (BY-FDR) |
| Study 3 E-Divisive changepoint (`4733e28..3d79fe9`) | `4733e28..fa91c31` | `64ad0b6..3d79fe9` | `64,000.0 ns -> 124,700.0 ns` | `+94.84%` | — | `0.005` (perm) |
| 30-pair pinned interleaved (`noise-bench`, batch=2; canary `+6.62%` `ENVIRONMENT_SUSPECT`) | `fa91c31` | `64ad0b6` | `64,000.0 ns -> 124,600.0 ns` | `+94.69%` | `[+94.69%, +94.69%]` | `1.01e-07` |
| 30-pair pinned interleaved to window head (`canary -2.66% OK`) | `fa91c31` | `3d79fe9` | `64,000.0 ns -> 124,600.0 ns` | `+94.69%` | `[+94.69%, +94.69%]` | `1.01e-07` |
| Standalone 2-rev Cargo repro (`reports/upstream/64ad0b6/repro/`) | `fa91c31` | `64ad0b6` | `64,000.0 ns -> 124,700.0 ns` | `+94.77%` | `[+94.69%, +94.85%]` | `1.48e-06` |

## Minimal Reproduction

A self-contained two-revision Cargo project is included at [`reports/upstream/64ad0b6/repro/`](repro/):

- [`repro/base/Cargo.toml`](repro/base/Cargo.toml): `regex = { git = "https://github.com/rust-lang/regex.git", rev = "fa91c31a4291c9dda6afe19829e6fe2e3bbc2da5" }`
- [`repro/cand/Cargo.toml`](repro/cand/Cargo.toml): `regex = { git = "https://github.com/rust-lang/regex.git", rev = "64ad0b618e043b791ed5385dd5504a436da1ddae" }`
- [`repro/src/main.rs`](repro/src/main.rs): Compiles `Regex::new(r".*.*=.*")` once and times `compiled.find_iter(black_box(hay)).map(|m| m.len()).sum::<usize>()` across a 10,001-byte haystack (`"x=" + "x".repeat(9998) + "\n"`), batched `2` calls per timed sample (`--iters 1000 --warmup 100`).

Run 30 randomized interleaved `AB`/`BA` pairs:

```bash
cd reports/upstream/64ad0b6/repro
python run_repro.py --pairs 30 --iters 1000 --warmup 100
```

## Environment

- **OS**: `Windows-11-10.0.26200-SP0 AMD64`
- **CPU**: `12th Gen Intel(R) Core(TM) i7-12650H` (Study 3 & `noise-bench` interleaved runs pinned to P-core `cpu_id=2` at `HIGH_PRIORITY_CLASS`)
- **Compiler**: `rustc 1.99.1 (58cf8f9c3 2026-10-13)`, host `x86_64-pc-windows-gnu`, LLVM `23.1.1` (`lto = true`, `codegen-units = 1`, `debug = true`)
- **Differential Flamegraph**: [`assets/flamegraphs/flamegraph_diff_64ad0b6.svg`](../../../assets/flamegraphs/flamegraph_diff_64ad0b6.svg) (`noise-bench/profiles/parent_fa91c31_redos.folded`, `noise-bench/profiles/candidate_64ad0b6_redos.folded`)
