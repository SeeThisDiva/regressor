//! Native Rust microbenchmark harness for `rust-lang/regex`.
//!
//! Usage:
//!   noise-bench [bench_name] [iters] [warmup] [inject_ns] [--pmu | --format=raw|csv|json]
//!   noise-bench --list-benchmarks
//!
//! Benchmarks include the 3 legacy study benchmarks (`find_iter_userid`,
//! `is_match_status`, `compile_moderate`) plus 22 benchmarks derived from
//! `BurntSushi/rebar`.

mod rebar;

use regex::Regex;
use std::hint::black_box;
use std::time::Instant;

pub const BENCHMARKS: &[&str] = &[
    "find_iter_userid",
    "is_match_status",
    "compile_moderate",
    "rebar_curated_01_literal_sherlock_en",
    "rebar_curated_01_literal_sherlock_casei_en",
    "rebar_curated_02_literal_alternate_sherlock_en",
    "rebar_curated_02_literal_alternate_sherlock_casei_ru",
    "rebar_curated_03_date_unicode",
    "rebar_curated_04_ruff_noqa_real",
    "rebar_curated_04_ruff_noqa_tweaked_lite",
    "rebar_curated_05_lexer_veryl_single",
    "rebar_curated_05_lexer_veryl_regexset",
    "rebar_curated_06_cloudflare_redos_long",
    "rebar_curated_08_words_all_russian",
    "rebar_curated_09_aws_keys_quick",
    "rebar_curated_10_bounded_repeat_letters_ru",
    "rebar_curated_10_bounded_repeat_context",
    "rebar_curated_12_dictionary_single",
    "rebar_opt_onepass_first_three_words_en",
    "rebar_opt_backtrack_words_en",
    "rebar_opt_reverse_suffix_holmes",
    "rebar_opt_reverse_inner_email",
    "rebar_reported_i988_sql_injection_compile",
    "rebar_unicode_compile_one_letter",
    "rebar_wild_rustsec_cargo_audit_bytes",
];

#[derive(Debug, Clone, Copy)]
pub struct Measurement {
    pub elapsed_ns: u64,
    pub tsc_ticks: u64,
}

#[inline(always)]
pub fn read_tsc_ticks() -> u64 {
    #[cfg(target_arch = "x86_64")]
    unsafe {
        core::arch::x86_64::_rdtsc()
    }
    #[cfg(target_arch = "x86")]
    unsafe {
        core::arch::x86::_rdtsc()
    }
    #[cfg(not(any(target_arch = "x86_64", target_arch = "x86")))]
    {
        0
    }
}

#[inline(always)]
pub(crate) fn busy_wait_ns(inject_ns: u64) {
    if inject_ns == 0 {
        return;
    }
    let t0 = Instant::now();
    while (t0.elapsed().as_nanos() as u64) < inject_ns {
        black_box(0);
    }
}

/// Times `iters` executions of `body`, capturing wall-clock nanoseconds and RDTSC ticks.
/// `body` returns its live result so any Drop happens after timing ends.
#[inline(always)]
pub(crate) fn measure_iterations<R, F: FnMut() -> R>(iters: u32, mut body: F) -> Vec<Measurement> {
    (0..iters)
        .map(|_| {
            let c0 = read_tsc_ticks();
            let start = Instant::now();
            let out = body();
            let elapsed_ns = start.elapsed().as_nanos() as u64;
            let c1 = read_tsc_ticks();
            black_box(out);
            Measurement {
                elapsed_ns,
                tsc_ticks: c1.saturating_sub(c0),
            }
        })
        .collect()
}

fn haystack() -> String {
    let line = "2026-08-13T10:22:31Z INFO service=auth user_id=48213 action=login \
                status=success latency_ms=42 ip=10.0.4.18\n";
    line.repeat(2000)
}

fn bench_compile(iters: u32, inject_ns: u64) -> Vec<Measurement> {
    measure_iterations(iters, || {
        let re = Regex::new(
            r"(?x)
            ^(?P<ts>\S+)\s+
            (?P<level>\w+)\s+
            service=(?P<service>\w+)\s+
            user_id=(?P<uid>\d+)\s+
            action=(?P<action>\w+)\s+
            status=(?P<status>\w+)\s+
            latency_ms=(?P<lat>\d+)\s+
            ip=(?P<ip>\S+)$",
        )
        .unwrap();
        busy_wait_ns(inject_ns);
        re
    })
}

fn bench_find_all(iters: u32, inject_ns: u64) -> Vec<Measurement> {
    let re = Regex::new(r"user_id=(\d+)").unwrap();
    let hay = haystack();
    measure_iterations(iters, || {
        let count = re.find_iter(black_box(&hay)).count();
        busy_wait_ns(inject_ns);
        count
    })
}

// is_match on this haystack short-circuits almost instantly (~50ns), which is
// below Instant::now()'s resolution/call overhead on many platforms -- measuring
// a single call would time the clock rather than the regex. Batch IS_MATCH_BATCH
// calls per timed sample so each measurement sits well above the timer floor.
const IS_MATCH_BATCH: u32 = 500;

fn bench_is_match(iters: u32, inject_ns: u64) -> Vec<Measurement> {
    let re = Regex::new(r"status=success").unwrap();
    let hay = haystack();
    measure_iterations(iters, || {
        for _ in 0..IS_MATCH_BATCH {
            black_box(re.is_match(black_box(&hay)));
        }
        busy_wait_ns(inject_ns);
    })
}

fn run_bench(bench_name: &str, iters: u32, inject_ns: u64) -> Result<Vec<Measurement>, String> {
    match bench_name {
        "compile_moderate" => Ok(bench_compile(iters, inject_ns)),
        "find_iter_userid" => Ok(bench_find_all(iters, inject_ns)),
        "is_match_status" => Ok(bench_is_match(iters, inject_ns)),
        other => rebar::run_rebar_bench(other, iters, inject_ns)
            .ok_or_else(|| format!("unknown bench: {other} (run with --list-benchmarks)")),
    }
}

fn parse_pos_int<T: std::str::FromStr>(raw: Option<&&str>, default: T, name: &str) -> Result<T, String> {
    match raw {
        None => Ok(default),
        Some(s) => s
            .parse::<T>()
            .map_err(|_| format!("invalid {name}: {s:?} (expected a non-negative integer)")),
    }
}

fn print_benchmarks() {
    for name in BENCHMARKS {
        println!("{name}");
    }
}

fn print_usage() {
    eprintln!(
        "Usage: noise-bench [bench_name] [iters] [warmup] [inject_ns] [--pmu | --format=raw|csv|json]\n\
         \x20      noise-bench --list-benchmarks\n\
         \n\
         Defaults: bench=find_iter_userid, iters=2000, warmup=200, inject_ns=0, --format=raw\n\
         \n\
         Benchmarks ({}):",
        BENCHMARKS.len()
    );
    for name in BENCHMARKS {
        eprintln!("  {name}");
    }
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.iter().any(|a| a == "-h" || a == "--help") {
        print_usage();
        return;
    }
    if args.iter().any(|a| a == "--list-benchmarks" || a == "list-benchmarks") {
        print_benchmarks();
        return;
    }

    let mut positional: Vec<&str> = Vec::new();
    let mut output_format = "raw";
    for arg in &args {
        if arg == "--pmu" || arg == "--format=csv" {
            output_format = "csv";
        } else if let Some(fmt) = arg.strip_prefix("--format=") {
            match fmt {
                "raw" | "csv" | "json" => output_format = fmt,
                other => {
                    eprintln!("unknown format: {other} (expected raw, csv, or json)");
                    std::process::exit(1);
                }
            }
        } else if arg.starts_with('-') {
            eprintln!("unknown flag: {arg} (run with --help for usage)");
            std::process::exit(1);
        } else {
            positional.push(arg.as_str());
        }
    }

    let bench_name = positional.first().copied().unwrap_or("find_iter_userid");
    let iters = match parse_pos_int(positional.get(1), 2000u32, "iters") {
        Ok(v) => v,
        Err(msg) => {
            eprintln!("{msg}");
            std::process::exit(1);
        }
    };
    let warmup = match parse_pos_int(positional.get(2), 200u32, "warmup") {
        Ok(v) => v,
        Err(msg) => {
            eprintln!("{msg}");
            std::process::exit(1);
        }
    };
    // Synthetic overhead in nanoseconds, spun inside the timed region of every sample
    // so injected shifts undergo realistic OS scheduling and CPU noise.
    let inject_ns = match parse_pos_int(positional.get(3), 0u64, "inject_ns") {
        Ok(v) => v,
        Err(msg) => {
            eprintln!("{msg}");
            std::process::exit(1);
        }
    };

    // Warmup pass (discarded) to prime caches and branch predictors.
    if let Err(msg) = run_bench(bench_name, warmup, 0) {
        eprintln!("{msg}");
        std::process::exit(1);
    }

    let samples = match run_bench(bench_name, iters, inject_ns) {
        Ok(s) => s,
        Err(msg) => {
            eprintln!("{msg}");
            std::process::exit(1);
        }
    };

    match output_format {
        "csv" => {
            println!("elapsed_ns,tsc_ticks");
            for s in samples {
                println!("{},{}", s.elapsed_ns, s.tsc_ticks);
            }
        }
        "json" => {
            print!("[");
            for (i, s) in samples.iter().enumerate() {
                if i > 0 {
                    print!(",");
                }
                print!("{{\"elapsed_ns\":{},\"tsc_ticks\":{}}}", s.elapsed_ns, s.tsc_ticks);
            }
            println!("]");
        }
        _ => {
            // Default "raw": one nanosecond duration per line.
            for s in samples {
                println!("{}", s.elapsed_ns);
            }
        }
    }
}
