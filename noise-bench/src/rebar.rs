//! Rebar-derived benchmark definitions for `noise-bench`.
//!
//! Each benchmark corresponds directly to a benchmark in `BurntSushi/rebar`
//! (`benchmarks/definitions/**/*.toml`) and uses only stable `regex` 1.x and
//! `regex-lite` 0.1.x public APIs so it compiles across the entire target
//! commit history.

use regex::bytes::RegexBuilder as BytesRegexBuilder;
use regex::{Regex, RegexBuilder, RegexSet, RegexSetBuilder};
use regex_lite::RegexBuilder as LiteRegexBuilder;
use std::hint::black_box;

use crate::{busy_wait_ns, measure_iterations, Measurement};

const SIZE_LIMIT_BYTES: usize = 100 * (1 << 20);

const HAY_EN_SAMPLED: &str = include_str!("../haystacks/en-sampled-2500.txt");
const HAY_EN_MEDIUM: &str = include_str!("../haystacks/en-medium.txt");
const HAY_RU_SAMPLED: &str = include_str!("../haystacks/ru-sampled-2500.txt");
const HAY_SHERLOCK: &str = include_str!("../haystacks/sherlock-2500.txt");
const HAY_BSTR: &str = include_str!("../haystacks/bstr-ext-slice-65993b58.txt");
const HAY_RUST_SRC: &str = include_str!("../haystacks/rust-src-tools-slice.txt");
const HAY_CPYTHON: &str = include_str!("../haystacks/cpython-noqa-slice.py");
const HAY_VERYL: &str = include_str!("../haystacks/parol-veryl-1500.vl");
const HAY_REDOS: &str = include_str!("../haystacks/cloud-flare-redos.txt");

const PAT_DATE: &str = include_str!("../haystacks/date-pattern.txt");
const PAT_DICT_15: &str = include_str!("../haystacks/dict-length-15.txt");
const PAT_VERYL_LINES: &str = include_str!("../haystacks/parol-veryl-patterns.txt");

/// Return a deterministic UTF-8 sub-slice covering lines `[start_line, end_line)`.
fn slice_lines(hay: &str, start_line: usize, end_line: usize) -> &str {
    let bytes = hay.as_bytes();
    let mut line = 0usize;
    let mut start_byte = if start_line == 0 { 0 } else { bytes.len() };
    let mut end_byte = bytes.len();
    for (idx, &b) in bytes.iter().enumerate() {
        if b == b'\n' {
            line += 1;
            if line == start_line && start_line > 0 {
                start_byte = idx + 1;
            }
            if line == end_line {
                end_byte = idx + 1;
                break;
            }
        }
    }
    if start_byte >= end_byte {
        ""
    } else {
        &hay[start_byte..end_byte]
    }
}

#[inline(always)]
fn count_matches_batched(
    iters: u32,
    inject_ns: u64,
    batch: u32,
    re: &Regex,
    hay: &str,
) -> Vec<Measurement> {
    measure_iterations(iters, || {
        let mut acc = 0usize;
        for _ in 0..batch {
            acc = acc.wrapping_add(black_box(re).find_iter(black_box(hay)).count());
        }
        busy_wait_ns(inject_ns);
        acc
    })
}

#[inline(always)]
fn count_spans_batched(
    iters: u32,
    inject_ns: u64,
    batch: u32,
    re: &Regex,
    hay: &str,
) -> Vec<Measurement> {
    measure_iterations(iters, || {
        let mut acc = 0usize;
        for _ in 0..batch {
            let sum: usize = black_box(re)
                .find_iter(black_box(hay))
                .map(|m| m.len())
                .sum();
            acc = acc.wrapping_add(sum);
        }
        busy_wait_ns(inject_ns);
        acc
    })
}

#[inline(always)]
fn grep_is_match_batched(
    iters: u32,
    inject_ns: u64,
    batch: u32,
    re: &Regex,
    hay: &str,
) -> Vec<Measurement> {
    measure_iterations(iters, || {
        let mut acc = 0usize;
        for _ in 0..batch {
            let mut count = 0usize;
            for line in black_box(hay).lines() {
                if black_box(re).is_match(line) {
                    count += 1;
                }
            }
            acc = acc.wrapping_add(count);
        }
        busy_wait_ns(inject_ns);
        acc
    })
}

#[inline(always)]
fn grep_captures_batched(
    iters: u32,
    inject_ns: u64,
    batch: u32,
    re: &Regex,
    hay: &str,
) -> Vec<Measurement> {
    let mut locs = re.capture_locations();
    measure_iterations(iters, || {
        let mut acc = 0usize;
        for _ in 0..batch {
            let mut count = 0usize;
            for line in black_box(hay).lines() {
                let mut at = 0usize;
                while let Some(m) = black_box(re).captures_read_at(&mut locs, line, at) {
                    for i in 0..locs.len() {
                        if locs.get(i).is_some() {
                            count += 1;
                        }
                    }
                    at = if m.end() > at { m.end() } else { at + 1 };
                    if at > line.len() {
                        break;
                    }
                }
            }
            acc = acc.wrapping_add(count);
        }
        busy_wait_ns(inject_ns);
        acc
    })
}

fn build_regex(pat: &str, case_insensitive: bool, unicode: bool) -> Regex {
    RegexBuilder::new(pat)
        .case_insensitive(case_insensitive)
        .unicode(unicode)
        .size_limit(SIZE_LIMIT_BYTES)
        .build()
        .unwrap()
}

fn build_dictionary_pattern() -> String {
    let mut joined = String::with_capacity(PAT_DICT_15.len() + 4096);
    for (i, line) in PAT_DICT_15.lines().filter(|l| !l.is_empty()).enumerate() {
        if i > 0 {
            joined.push('|');
        }
        joined.push_str(&regex::escape(line));
    }
    joined
}

fn build_veryl_patterns() -> Vec<&'static str> {
    PAT_VERYL_LINES.lines().filter(|l| !l.is_empty()).collect()
}

fn build_veryl_alternation() -> String {
    build_veryl_patterns().join("|")
}

/// Deterministic ~64 KB binary haystack containing non-UTF-8 bytes alongside
/// `cargo/registry/src/...` paths for `bytes::Regex` benchmarking.
fn build_rustsec_binary_haystack() -> Vec<u8> {
    let mut buf = Vec::with_capacity(64 * 1024);
    let mut state: u32 = 0x9E37_79B9;
    let paths: [&[u8]; 3] = [
        b"\x00cargo/registry/src/index.crates.io-6f17d22bba15001f/memchr-2.8.3/src/lib.rs\x00",
        b"\x00cargo\\registry\\src\\index.crates.io-6f17d22bba15001f\\aho-corasick-1.1.5\\src\\lib.rs\x00",
        b"\x00cargo/registry/src/github.com-1ecc6299db9ec823/regex-automata-0.4.13/src/meta/regex.rs\x00",
    ];
    for chunk_idx in 0..1024 {
        if chunk_idx % 128 == 64 {
            buf.extend_from_slice(paths[(chunk_idx / 128) % paths.len()]);
        } else {
            // Generate pseudo-random bytes including invalid UTF-8 sequences (0x80..=0xFF).
            for _ in 0..64 {
                state = state.wrapping_mul(1664525).wrapping_add(1013904223);
                let byte = ((state >> 16) & 0xFF) as u8;
                // Avoid accidental 'c' floods that mimic "cargo"
                buf.push(if byte == b'c' { 0xFF } else { byte });
            }
        }
    }
    buf
}

fn bench_ruff_noqa_tweaked_lite(iters: u32, inject_ns: u64, batch: u32) -> Vec<Measurement> {
    let re = LiteRegexBuilder::new(
        r"(?:# [Nn][Oo][Qq][Aa])(?::\s?(([A-Z]+[0-9]+(?:[,\s]+)?)+))?",
    )
    .size_limit(SIZE_LIMIT_BYTES)
    .build()
    .unwrap();
    let hay = slice_lines(HAY_CPYTHON, 850, 1150);
    let mut locs = re.capture_locations();
    measure_iterations(iters, || {
        let mut acc = 0usize;
        for _ in 0..batch {
            let mut count = 0usize;
            for line in black_box(hay).lines() {
                let mut at = 0usize;
                while let Some(m) = black_box(&re).captures_read_at(&mut locs, line, at) {
                    for i in 0..locs.len() {
                        if locs.get(i).is_some() {
                            count += 1;
                        }
                    }
                    at = if m.end() > at { m.end() } else { at + 1 };
                    if at > line.len() {
                        break;
                    }
                }
            }
            acc = acc.wrapping_add(count);
        }
        busy_wait_ns(inject_ns);
        acc
    })
}

fn bench_lexer_veryl_single(iters: u32, inject_ns: u64, batch: u32) -> Vec<Measurement> {
    let pat = build_veryl_alternation();
    let re = build_regex(&pat, false, true);
    let hay = slice_lines(HAY_VERYL, 0, 80);
    measure_iterations(iters, || {
        let mut acc = 0usize;
        for _ in 0..batch {
            let mut count = 0usize;
            for caps in black_box(&re).captures_iter(black_box(hay)) {
                for g in caps.iter() {
                    if g.is_some() {
                        count += 1;
                    }
                }
            }
            acc = acc.wrapping_add(count);
        }
        busy_wait_ns(inject_ns);
        acc
    })
}

fn bench_lexer_veryl_regexset(iters: u32, inject_ns: u64, batch: u32) -> Vec<Measurement> {
    let pats = build_veryl_patterns();
    let set: RegexSet = RegexSetBuilder::new(pats)
        .unicode(true)
        .size_limit(SIZE_LIMIT_BYTES)
        .build()
        .unwrap();
    let hay = slice_lines(HAY_VERYL, 0, 600);
    measure_iterations(iters, || {
        let mut acc = 0usize;
        for _ in 0..batch {
            let mut count = 0usize;
            for line in black_box(hay).lines() {
                count += black_box(&set).matches(line).iter().count();
            }
            acc = acc.wrapping_add(count);
        }
        busy_wait_ns(inject_ns);
        acc
    })
}

fn bench_compile_pattern(
    iters: u32,
    inject_ns: u64,
    batch: u32,
    pat: &str,
    case_insensitive: bool,
    unicode: bool,
) -> Vec<Measurement> {
    measure_iterations(iters, || {
        let mut last = None;
        for _ in 0..batch {
            let re = RegexBuilder::new(black_box(pat))
                .case_insensitive(case_insensitive)
                .unicode(unicode)
                .size_limit(SIZE_LIMIT_BYTES)
                .build()
                .unwrap();
            last = Some(black_box(re));
        }
        busy_wait_ns(inject_ns);
        last
    })
}

fn bench_rustsec_bytes(iters: u32, inject_ns: u64, batch: u32) -> Vec<Measurement> {
    let pat = r"cargo[\\/]registry[\\/]src[\\/][^\\/]+[\\/]([0-9A-Za-z_-]+)-([0-9]+\.[0-9]+\.[0-9]+[0-9A-Za-z+.-]*)[\\/]";
    let re = BytesRegexBuilder::new(pat)
        .unicode(false)
        .size_limit(SIZE_LIMIT_BYTES)
        .build()
        .unwrap();
    let hay = build_rustsec_binary_haystack();
    let mut locs = re.capture_locations();
    measure_iterations(iters, || {
        let mut acc = 0usize;
        for _ in 0..batch {
            let mut count = 0usize;
            let mut at = 0usize;
            while let Some(m) = black_box(&re).captures_read_at(&mut locs, black_box(&hay), at) {
                for i in 0..locs.len() {
                    if locs.get(i).is_some() {
                        count += 1;
                    }
                }
                at = if m.end() > at { m.end() } else { at + 1 };
                if at > hay.len() {
                    break;
                }
            }
            acc = acc.wrapping_add(count);
        }
        busy_wait_ns(inject_ns);
        acc
    })
}

pub fn run_rebar_bench(
    bench_name: &str,
    iters: u32,
    inject_ns: u64,
) -> Option<Vec<Measurement>> {
    let samples = match bench_name {
        "rebar_curated_01_literal_sherlock_en" => {
            let re = build_regex("Sherlock Holmes", false, false);
            count_matches_batched(iters, inject_ns, 8, &re, HAY_EN_SAMPLED)
        }
        "rebar_curated_01_literal_sherlock_casei_en" => {
            let re = build_regex("Sherlock Holmes", true, false);
            count_matches_batched(iters, inject_ns, 4, &re, HAY_EN_SAMPLED)
        }
        "rebar_curated_02_literal_alternate_sherlock_en" => {
            let re = build_regex(
                "Sherlock Holmes|John Watson|Irene Adler|Inspector Lestrade|Professor Moriarty",
                false,
                false,
            );
            count_matches_batched(iters, inject_ns, 4, &re, HAY_EN_SAMPLED)
        }
        "rebar_curated_02_literal_alternate_sherlock_casei_ru" => {
            let re = build_regex(
                "Шерлок Холмс|Джон Уотсон|Ирен Адлер|инспектор Лестрейд|профессор Мориарти",
                true,
                true,
            );
            count_matches_batched(iters, inject_ns, 1, &re, HAY_RU_SAMPLED)
        }
        "rebar_curated_03_date_unicode" => {
            let re = build_regex(PAT_DATE.trim(), true, true);
            let hay = slice_lines(HAY_RUST_SRC, 0, 1000);
            count_spans_batched(iters, inject_ns, 1, &re, hay)
        }
        "rebar_curated_04_ruff_noqa_real" => {
            let re = build_regex(
                r"(\s*)((?:# [Nn][Oo][Qq][Aa])(?::\s?(([A-Z]+[0-9]+(?:[,\s]+)?)+))?)",
                false,
                false,
            );
            grep_captures_batched(iters, inject_ns, 1, &re, HAY_CPYTHON)
        }
        "rebar_curated_04_ruff_noqa_tweaked_lite" => {
            bench_ruff_noqa_tweaked_lite(iters, inject_ns, 1)
        }
        "rebar_curated_05_lexer_veryl_single" => bench_lexer_veryl_single(iters, inject_ns, 1),
        "rebar_curated_05_lexer_veryl_regexset" => {
            bench_lexer_veryl_regexset(iters, inject_ns, 1)
        }
        "rebar_curated_06_cloudflare_redos_long" => {
            let re = build_regex(r".*.*=.*", false, true);
            count_spans_batched(iters, inject_ns, 2, &re, HAY_REDOS)
        }
        "rebar_curated_08_words_all_russian" => {
            let re = build_regex(r"\b\w+\b", false, true);
            let hay = slice_lines(HAY_RU_SAMPLED, 0, 50);
            count_spans_batched(iters, inject_ns, 1, &re, hay)
        }
        "rebar_curated_09_aws_keys_quick" => {
            let re = build_regex(r"((?:ASIA|AKIA|AROA|AIDA)([A-Z0-7]{16}))", false, false);
            grep_is_match_batched(iters, inject_ns, 1, &re, HAY_CPYTHON)
        }
        "rebar_curated_10_bounded_repeat_letters_ru" => {
            let re = build_regex(r"\p{L}{8,13}", false, true);
            count_matches_batched(iters, inject_ns, 1, &re, HAY_RU_SAMPLED)
        }
        "rebar_curated_10_bounded_repeat_context" => {
            let re = build_regex(
                r"[A-Za-z]{10}\s+[\s\S]{0,100}Result[\s\S]{0,100}\s+[A-Za-z]{10}",
                false,
                true,
            );
            count_matches_batched(iters, inject_ns, 1, &re, HAY_BSTR)
        }
        "rebar_curated_12_dictionary_single" => {
            let pat = build_dictionary_pattern();
            let re = build_regex(&pat, false, false);
            count_matches_batched(iters, inject_ns, 1, &re, HAY_EN_MEDIUM)
        }
        "rebar_opt_onepass_first_three_words_en" => {
            let re = build_regex(r"^ *(\w+) +(\w+) +(\w+)", false, false);
            let hay = slice_lines(HAY_EN_MEDIUM, 0, 1000);
            grep_captures_batched(iters, inject_ns, 1, &re, hay)
        }
        "rebar_opt_backtrack_words_en" => {
            let re = build_regex(r"\b(?:(\w{6})|(\w{5}))\b", false, false);
            let hay = slice_lines(HAY_EN_MEDIUM, 0, 500);
            grep_captures_batched(iters, inject_ns, 1, &re, hay)
        }
        "rebar_opt_reverse_suffix_holmes" => {
            let re = build_regex(r"\w+\s+Holmes", false, false);
            count_spans_batched(iters, inject_ns, 2, &re, HAY_SHERLOCK)
        }
        "rebar_opt_reverse_inner_email" => {
            let re = build_regex(r"\w+@\w+", false, false);
            count_spans_batched(iters, inject_ns, 16, &re, HAY_RUST_SRC)
        }
        "rebar_reported_i988_sql_injection_compile" => bench_compile_pattern(
            iters,
            inject_ns,
            1,
            r"(?i:(?:(?:n(?:and|ot)|(?:x?x)?or|between|\|\||like|and|div|&&)\s+\s*?\w+\(|\)\s*?when\s*?\d+\s*?then|[`]\s*?(?:--|\{|#)|cha?r\s*?\(\s*?\d|/\*!\s?\d+))",
            false,
            false,
        ),
        "rebar_unicode_compile_one_letter" => {
            bench_compile_pattern(iters, inject_ns, 1, r"\pL", false, true)
        }
        "rebar_wild_rustsec_cargo_audit_bytes" => bench_rustsec_bytes(iters, inject_ns, 4),
        _ => return None,
    };
    Some(samples)
}
