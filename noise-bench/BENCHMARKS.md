# `noise-bench` Benchmark Suite (`rust-lang/regex`)

`noise-bench` runs **25 benchmarks**: the **3 legacy Study 1/2 microbenchmarks** (preserved verbatim so historical datasets remain comparable) plus **22 benchmarks derived from [`BurntSushi/rebar`](https://github.com/BurntSushi/rebar)** (`benchmarks/definitions/**/*.toml`).

## Harness Semantics

Every benchmark obeys the same measurement contract:

- **Timing unit**: Wall-clock nanoseconds (`Instant::now()`) and x86/x86_64 `_rdtsc` ticks per timed iteration (`--format=raw|csv|json`, `--pmu`).
- **Batching**: Fast operations are batched (`BATCH` inner iterations per timed sample) so every sample comfortably exceeds the Windows/Linux timer resolution floor (`>= ~25 us` per sample on local hardware, well above the `>= ~5 us` minimum).
- **Synthetic slowdown injection**: `busy_wait_ns(inject_ns)` executes **once per timed sample inside the timed closure** (before `start.elapsed()`), ensuring `regressor validate-adapter` sees an exact `1x` additive CPU-work shift without artificial batch amplification.
- **Warmup & drop isolation**: `warmup` untimed iterations prime caches and branch predictors before measurement; live outputs (`usize` accumulator or compiled `Regex`) are returned from the timed closure and `black_box`-ed so destructors run outside the timed interval.
- **Compatibility**: Only stable public `regex` 1.x (`regex::Regex`, `regex::RegexBuilder`, `regex::RegexSet`, `regex::bytes::Regex`) and `regex-lite` 0.1.x (`regex_lite::RegexBuilder`) APIs are used, compiling across the full `cf00423..3d79fe9` (Aug 2025 – Nov 2026) commit range and upstream `master`.
- **Listing**: `noise-bench --list-benchmarks` (or `noise-bench list-benchmarks`) prints all 25 benchmark names; `RegexAdapter.list_benchmarks()` reads `projects/regex.toml` directly.

## Benchmark Inventory & Rebar Mapping

| # | Benchmark Name | Origin | Code Path Exercised | API / Model | Haystack | Inner Batch |
|---:|---|---|---|---|---|---:|
| 1 | `find_iter_userid` | Legacy Study 1/2 | `Regex::find_iter` on structured log lines | `Regex::find_iter().count()` | Synthetic 2,000-line log | 1 |
| 2 | `is_match_status` | Legacy Study 1/2 | `Regex::is_match` early-exit literal match | `Regex::is_match` | Synthetic 2,000-line log | 500 |
| 3 | `compile_moderate` | Legacy Study 1/2 | Moderate named-capture pattern compilation | `Regex::new` | — | 1 |
| 4 | `rebar_curated_01_literal_sherlock_en` | `rebar/curated/01-literal/sherlock-en` | Single-literal prefilter (`memchr` / `memmem`) | `Regex::find_iter().count()` (`unicode=false`) | `en-sampled-2500.txt` | 8 |
| 5 | `rebar_curated_01_literal_sherlock_casei_en` | `rebar/curated/01-literal/sherlock-casei-en` | ASCII case-insensitive literal prefilter (Teddy prefixes) | `Regex::find_iter().count()` (`ci=true, unicode=false`) | `en-sampled-2500.txt` | 4 |
| 6 | `rebar_curated_02_literal_alternate_sherlock_en` | `rebar/curated/02-literal-alternate/sherlock-en` | Multi-literal alternation prefilter (Teddy SIMD) | `Regex::find_iter().count()` (`unicode=false`) | `en-sampled-2500.txt` | 4 |
| 7 | `rebar_curated_02_literal_alternate_sherlock_casei_ru` | `rebar/curated/02-literal-alternate/sherlock-casei-ru` | Unicode case-folding + Cyrillic multi-literal alternation | `Regex::find_iter().count()` (`ci=true, unicode=true`) | `ru-sampled-2500.txt` | 1 |
| 8 | `rebar_curated_03_date_unicode` | `rebar/curated/03-date/unicode` | Lazy DFA over large tokenizer regex + Unicode `\d`/`\s` | `Regex::find_iter().map(\|m\| m.len()).sum()` | `rust-src-tools-slice.txt` (1,000 lines) | 1 |
| 9 | `rebar_curated_04_ruff_noqa_real` | `rebar/curated/04-ruff-noqa/real` | Line grep-captures with reverse-inner prefilter + fast reject | `Regex::captures_read_at` per line | `cpython-noqa-slice.py` | 1 |
| 10 | `rebar_curated_04_ruff_noqa_tweaked_lite` | `rebar/curated/04-ruff-noqa/tweaked` (`rust/regex/lite`) | `regex-lite` compiler and PikeVM capture engine | `regex_lite::Regex::captures_read_at` per line | `cpython-noqa-slice.py` (300-line slice) | 1 |
| 11 | `rebar_curated_05_lexer_veryl_single` | `rebar/curated/05-lexer-veryl/single` | 88-branch lexer alternation with high-density `captures_iter` | `Regex::captures_iter` (`unicode=true`) | `parol-veryl-1500.vl` (80 lines) | 1 |
| 12 | `rebar_curated_05_lexer_veryl_regexset` | `rebar/curated/05-lexer-veryl/multi` | Multi-pattern `RegexSet` matching across 88 token patterns | `RegexSet::matches` per line | `parol-veryl-1500.vl` (600 lines) | 1 |
| 13 | `rebar_curated_06_cloudflare_redos_long` | `rebar/curated/06-cloud-flare-redos/simplified-long` | Linear-time full DFA + state acceleration on ReDoS pattern | `Regex::find_iter().map(\|m\| m.len()).sum()` | `cloud-flare-redos.txt` | 2 |
| 14 | `rebar_curated_08_words_all_russian` | `rebar/curated/08-words/all-russian` | Unicode `\w` and Unicode `\b` word boundary on non-ASCII text | `Regex::find_iter().map(\|m\| m.len()).sum()` | `ru-sampled-2500.txt` (50 lines) | 1 |
| 15 | `rebar_curated_09_aws_keys_quick` | `rebar/curated/09-aws-keys/quick` | Line-oriented `is_match` fast-reject via 4-literal prefix | `Regex::is_match` per line | `cpython-noqa-slice.py` | 1 |
| 16 | `rebar_curated_10_bounded_repeat_letters_ru` | `rebar/curated/10-bounded-repeat/letters-ru` | Large Unicode `\p{L}` class with `{8,13}` bounded repeat | `Regex::find_iter().count()` (`unicode=true`) | `ru-sampled-2500.txt` | 1 |
| 17 | `rebar_curated_10_bounded_repeat_context` | `rebar/curated/10-bounded-repeat/context` | Lazy DFA cache pressure from `[\s\S]{0,100}` bounded repeat | `Regex::find_iter().count()` (`unicode=true`) | `bstr-ext-slice-65993b58.txt` | 1 |
| 18 | `rebar_curated_12_dictionary_single` | `rebar/curated/12-dictionary/single` | 2,663-word literal alternation trie rewrite + Aho-Corasick | `Regex::find_iter().count()` (`unicode=false`) | `en-medium.txt` | 1 |
| 19 | `rebar_opt_onepass_first_three_words_en` | `rebar/opt/onepass/first-three-words-english` | One-Pass DFA capture extraction (`^ *(\w+) +(\w+) +(\w+)`) | `Regex::captures_read_at` per line | `en-medium.txt` (1,000 lines) | 1 |
| 20 | `rebar_opt_backtrack_words_en` | `rebar/opt/backtrack/words-english` | BoundedBacktracker capture extraction (`\b(?:(\w{6})\|(\w{5}))\b`) | `Regex::captures_read_at` per line | `en-medium.txt` (500 lines) | 1 |
| 21 | `rebar_opt_reverse_suffix_holmes` | `rebar/opt/reverse-suffix/holmes` | Reverse-Suffix optimization (`\w+\s+Holmes`) | `Regex::find_iter().map(\|m\| m.len()).sum()` | `sherlock-2500.txt` | 2 |
| 22 | `rebar_opt_reverse_inner_email` | `rebar/opt/reverse-inner/email` | Reverse-Inner optimization (`\w+@\w+`) | `Regex::find_iter().map(\|m\| m.len()).sum()` | `rust-src-tools-slice.txt` | 16 |
| 23 | `rebar_reported_i988_sql_injection_compile` | `rebar/reported/i988-cloudflare-compile/sql-injection` | Small/medium ASCII pattern AST->HIR + NFA compile | `RegexBuilder::build()` (`unicode=false`) | — | 1 |
| 24 | `rebar_unicode_compile_one_letter` | `rebar/unicode/compile/one-letter` | Unicode `\pL` UTF-8 automaton + IntervalSet compilation | `RegexBuilder::build()` (`unicode=true`) | — | 1 |
| 25 | `rebar_wild_rustsec_cargo_audit_bytes` | `rebar/wild/rustsec-cargo-audit/both-slashes` | `regex::bytes::Regex` capture matching over non-UTF-8 binary data | `bytes::Regex::captures_read_at` | Deterministic 64 KB binary buffer | 4 |

## Haystacks & Attribution

All vendored haystacks and pattern fixtures live under `noise-bench/haystacks/` (~744 KB total; full attribution and truncation details in [`haystacks/README.md`](haystacks/README.md)).

## Cross-Commit Compatibility & Baseline Noise (5-Rep Measurement)

Verified isolated worktree builds (`RegexAdapter.build(..., workdir=...)`) + `--list-benchmarks` + sample smoke execution across:
- `cf00423` (14 Aug 2025, `regex 1.11.1` / `regex-lite 0.1.6`) — OK (`55.47s`)
- `5ea3eb1` (13 Oct 2025, `regex 1.12.2` / `regex-lite 0.1.8`) — OK (`56.35s`)
- `4733e28` (27 Jan 2026, `regex 1.12.2` / `regex-lite 0.1.8`) — OK (`53.90s`)
- `3d79fe9` (07 Nov 2026, `regex 1.13.1` / `regex-lite 0.1.9`) — OK (`51.53s`)
- `4226f21` (17 Nov 2026, `regex 1.13.2` / `regex-lite 0.1.9`) — OK (`105.11s`)

Measured 5-rep baseline on `./regex` at `4733e28` (`iters=2000`, `warmup=200`, unpinned Windows 11 host; total 5-rep wall time `107.72s`, **`21.54s` per rep** across all 25 benchmarks):

| Benchmark | 5-Rep Median (ns) | 5-Rep CV (%) | 5-Rep Wall (s) |
|---|---:|---:|---:|
| `find_iter_userid` | 129,100.0 | 0.32% | 1.59 |
| `is_match_status` | 25,300.0 | 1.51% | 0.43 |
| `compile_moderate` | 2,584,400.0 | 7.27% | 40.31 |
| `rebar_curated_01_literal_sherlock_en` | 36,600.0 | 0.43% | 0.56 |
| `rebar_curated_01_literal_sherlock_casei_en` | 49,500.0 | 0.11% | 0.70 |
| `rebar_curated_02_literal_alternate_sherlock_en` | 48,100.0 | 0.15% | 0.68 |
| `rebar_curated_02_literal_alternate_sherlock_casei_ru` | 86,200.0 | 1.15% | 1.20 |
| `rebar_curated_03_date_unicode` | 381,200.0 | 0.30% | 4.76 |
| `rebar_curated_04_ruff_noqa_real` | 124,300.0 | 0.59% | 1.59 |
| `rebar_curated_04_ruff_noqa_tweaked_lite` | 302,300.0 | 5.84% | 3.65 |
| `rebar_curated_05_lexer_veryl_single` | 625,800.0 | 0.34% | 7.27 |
| `rebar_curated_05_lexer_veryl_regexset` | 456,000.0 | 0.35% | 5.35 |
| `rebar_curated_06_cloudflare_redos_long` | 64,000.0 | 0.00% | 0.88 |
| `rebar_curated_08_words_all_russian` | 517,750.0 | 0.29% | 5.95 |
| `rebar_curated_09_aws_keys_quick` | 139,400.0 | 0.36% | 1.76 |
| `rebar_curated_10_bounded_repeat_letters_ru` | 423,300.0 | 0.16% | 4.94 |
| `rebar_curated_10_bounded_repeat_context` | 471,600.0 | 0.63% | 5.47 |
| `rebar_curated_12_dictionary_single` | 195,800.0 | 0.27% | 2.71 |
| `rebar_opt_onepass_first_three_words_en` | 151,700.0 | 0.48% | 1.87 |
| `rebar_opt_backtrack_words_en` | 167,500.0 | 0.78% | 2.13 |
| `rebar_opt_reverse_suffix_holmes` | 30,100.0 | 0.43% | 0.48 |
| `rebar_opt_reverse_inner_email` | 36,700.0 | 5.27% | 0.53 |
| `rebar_reported_i988_sql_injection_compile` | 499,200.0 | 1.29% | 6.09 |
| `rebar_unicode_compile_one_letter` | 460,700.0 | 5.52% | 5.98 |
| `rebar_wild_rustsec_cargo_audit_bytes` | 53,100.0 | 1.87% | 0.83 |

