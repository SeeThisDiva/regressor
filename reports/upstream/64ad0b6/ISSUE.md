<!-- Pre-filing checklist (do not file until checked):
- [ ] Read upstream issues/PRs #1354, #1355, and #1364 on rust-lang/regex.
- [ ] Search upstream issues for `cloud-flare-redos`, `.*.*=.*`, and `reverse inner`.
- [ ] If a duplicate or existing tracking thread exists, comment there instead of opening a new issue.
-->

# Concrete Pattern Affected by the #1354 Fallback (`.*.*=.*`, `rebar` `cloud-flare-redos`), with Possible Mitigation

## Summary

Commit [`64ad0b6`](https://github.com/rust-lang/regex/commit/64ad0b618e043b791ed5385dd5504a436da1ddae) (`automata: fix bug in reverse suffix/inner optimization`, fixing `#1354`; detailed in the `1.13.1` changelog via `#1364`) made `ReverseInner` conservatively fall back to `Core` on `r".*.*=.*"`, adding `+94.7%` (~`1.95x`) runtime on `rebar`'s `curated/06-cloud-flare-redos/simplified-long` workload (`10,001`-byte `x=xxxx...` haystack on Windows).

As [`64ad0b6`](https://github.com/rust-lang/regex/commit/64ad0b618e043b791ed5385dd5504a436da1ddae) explains, the simpler alternative (`#1355`) would have nearly disabled the reverse suffix and inner optimizations entirely, so this change intentionally trades conservative fallbacks on some overlapping prefixes for leftmost-first match-span correctness:

> "This does unfortunately cause some regressions."

The commit message already documents `(.*?,){13}z` as one affected pattern. This note adds `.*.*=.*` (`cloud-flare-redos`) as another concrete pattern affected by the `#1354` fallback, along with a possible mitigation for unconstrained greedy wildcard prefixes.

## Which Callers Pay

`Regex::find_iter(...).count()` overrides `Iterator::count` via `Matches::count` -> `search_half` and skips the full reverse scan (`find_rev`), showing only a `+9.22%` (about `+9%`) forward-only cost in our measurements. Callers that consume match positions or slices via `find`, `find_iter`, or `captures` run both `find_fwd` and `find_rev` under `Core` and pay the full `+94.7%` cost.

## Root Cause Analysis

Prior to `64ad0b6` (at parent `fa91c31`), `r".*.*=.*"` selected `Strategy::ReverseInner`:

1. `preinner` (`Memchr` scanning for `b'='`) locates `'='` at offset `1`.
2. A 1-byte reverse check confirms `.*.*` back to offset `0`.
3. `stopat::hybrid_try_search_half_fwd` runs a single forward scan across the haystack (`64.0 us` for 2 batched searches, or `~32.0 us` per search).

In `64ad0b6`, `ReverseInner::new` calls `reverse_inner::has_no_earlier_match(&prefilter.prefix, &prefilter.literals)`, which calls `prefix::hir_can_contain_literal(&concat_prefix, b"=")`. Because `concat_prefix` is `.*.*` and `.` can match `b'='`, `has_no_earlier_match` returns `false` and `Strategy::new` falls back to `Core`:

- Without the inner prefilter, `Core::search` executes both a full-haystack forward scan (`hybrid::search::find_fwd`) and a full-haystack reverse scan (`hybrid::search::find_rev`) to resolve the match start offset, nearly doubling wall time (`64,000 ns -> 124,600 ns`).

Windows user-mode stack sampling (`assets/flamegraphs/flamegraph_diff_64ad0b6.svg`) directly observes this shift (`fa91c31` `2,225` samples / `3.412s` vs `64ad0b6` `4,330` samples / `6.863s`):

- **`fa91c31` (baseline)**: `2,168 / 2,225` samples (`97.44%`) in `ReverseInner::search -> stopat::hybrid_try_search_half_fwd`.
- **`64ad0b6` (candidate)**: `4,263 / 4,330` samples (`98.45%` inclusive) in `Core::search` (`4,261 / 4,330` or `98.41%` in `hybrid::regex::Regex::try_search`: `2,384` inclusive / `2,382` self samples = `55.06%` in `find_fwd` + `1,877` samples = `43.35%` in `find_rev`).

### Possible Mitigation Note

Because `.*.*` (at a top-level prefix without intervening restrictions and with a single literal `=`) matches any non-`\n` bytes greedily back to byte `0` (or the start of the line) from the first `=` found by `preinner`, no valid match on that line can start strictly earlier than the start found by reversing from that candidate. If a lightweight HIR check can recognize unconstrained greedy wildcard prefixes (or if such patterns remain routed through `Core` under the existing `#1354` trade-off), this note documents the concrete `rebar` case.

## Benchmark Measurements

| Measurement | Baseline | Candidate | Median (Base -> Cand) | Shift (HL) | 95% CI | Wilcoxon / Perm p |
|---|---|---|---|---|---|---|
| Year-long Study 3 transition (`51` commits, `25` benches) | `fa91c31` | `64ad0b6` | `64,100.0 ns -> 124,600.0 ns` | `+94.38%` | N/A | `1.86e-07` (BY-FDR) |
| Study 3 E-Divisive changepoint (`4733e28..3d79fe9`) | `4733e28..fa91c31` | `64ad0b6..3d79fe9` | `64,000.0 ns -> 124,700.0 ns` | `+94.84%` | N/A | `0.005` (perm) |
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

<!-- TODO(author): paste your own second-platform run here (WSL2 or the Docker container) -->
```bash
python run_repro.py --pairs 30 --iters 1000 --warmup 100
```

## Environment

- **OS**: `Windows-11-10.0.26200-SP0 AMD64`
- **CPU**: `12th Gen Intel(R) Core(TM) i7-12650H` (Study 3 & `noise-bench` interleaved runs pinned to P-core `cpu_id=2` at `HIGH_PRIORITY_CLASS`)
- **Compiler**: `rustc 1.99.1 (58cf8f9c3 2026-10-13)`, host `x86_64-pc-windows-gnu`, LLVM `23.1.1` (`lto = true`, `codegen-units = 1`, `debug = true`)
- **Differential Flamegraph**: [`assets/flamegraphs/flamegraph_diff_64ad0b6.svg`](../../../assets/flamegraphs/flamegraph_diff_64ad0b6.svg) (`noise-bench/profiles/parent_fa91c31_redos.folded`, `noise-bench/profiles/candidate_64ad0b6_redos.folded`)
