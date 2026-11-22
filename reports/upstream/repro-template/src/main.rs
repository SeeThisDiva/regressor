//! Standalone minimal reproducer for a `rust-lang/regex` performance shift.
//!
//! Usage:
//!   repro [iters] [warmup]

use regex::Regex;
use std::hint::black_box;
use std::time::Instant;

const PATTERN: &str = r#"__PATTERN__"#;
const HAYSTACK_SEED: &str = "__HAYSTACK_SEED__";
const HAYSTACK_REPEAT: usize = __HAYSTACK_REPEAT__;
const BATCH_SIZE: u32 = __BATCH_SIZE__;
const MODE: &str = "__BENCH_MODE__"; // "compile" | "find_iter" | "is_match" | "captures_iter"

fn build_haystack() -> String {
    HAYSTACK_SEED.repeat(HAYSTACK_REPEAT)
}

fn measure_one<R, F: FnMut() -> R>(mut body: F) -> u64 {
    let t0 = Instant::now();
    let out = body();
    let ns = t0.elapsed().as_nanos() as u64;
    black_box(out);
    ns
}

fn run_pass(iters: u32, mode: &str, hay: &str, re: Option<&Regex>) -> Vec<u64> {
    let mut out = Vec::with_capacity(iters as usize);
    match mode {
        "compile" => {
            for _ in 0..iters {
                out.push(measure_one(|| {
                    for _ in 0..BATCH_SIZE {
                        black_box(Regex::new(black_box(PATTERN)).unwrap());
                    }
                }));
            }
        }
        "is_match" => {
            let compiled = re.expect("compiled regex required");
            for _ in 0..iters {
                out.push(measure_one(|| {
                    let mut hits = 0usize;
                    for _ in 0..BATCH_SIZE {
                        if compiled.is_match(black_box(hay)) {
                            hits += 1;
                        }
                    }
                    hits
                }));
            }
        }
        "captures_iter" => {
            let compiled = re.expect("compiled regex required");
            for _ in 0..iters {
                out.push(measure_one(|| {
                    let mut total = 0usize;
                    for _ in 0..BATCH_SIZE {
                        total += compiled.captures_iter(black_box(hay)).count();
                    }
                    total
                }));
            }
        }
        _ => {
            // Default: "find_iter" (evaluates match spans, avoiding Matches::count half-search fast path)
            let compiled = re.expect("compiled regex required");
            for _ in 0..iters {
                out.push(measure_one(|| {
                    let mut total = 0usize;
                    for _ in 0..BATCH_SIZE {
                        total += compiled.find_iter(black_box(hay)).map(|m| m.len()).sum::<usize>();
                    }
                    total
                }));
            }
        }
    }
    out
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let iters: u32 = args.first().and_then(|s| s.parse().ok()).unwrap_or(2000);
    let warmup: u32 = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(200);

    let hay = build_haystack();
    let compiled = if MODE == "compile" {
        None
    } else {
        Some(Regex::new(PATTERN).expect("valid pattern"))
    };

    let _ = run_pass(warmup, MODE, &hay, compiled.as_ref());
    let samples = run_pass(iters, MODE, &hay, compiled.as_ref());
    for ns in samples {
        println!("{ns}");
    }
}
