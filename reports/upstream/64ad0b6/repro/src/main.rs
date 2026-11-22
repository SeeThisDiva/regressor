//! Standalone minimal reproducer for a `rust-lang/regex` performance shift.
//!
//! Usage:
//!   repro [iters] [warmup]

use regex::Regex;
use std::hint::black_box;
use std::time::Instant;

const PATTERN: &str = r#".*.*=.*"#;
const REDOS_SUFFIX_LEN: usize = 9998;
const BATCH_SIZE: u32 = 2;
const MODE: &str = "find_iter"; // matches rebar curated/06-cloud-flare-redos/simplified-long

fn build_haystack() -> String {
    // Matches rebar haystack `curated/06-cloud-flare-redos/cloud-flare-redos.txt` (10,001 bytes):
    // `"x=" + "x".repeat(9998) + "\n"`.
    let mut s = String::with_capacity(2 + REDOS_SUFFIX_LEN + 1);
    s.push_str("x=");
    for _ in 0..REDOS_SUFFIX_LEN {
        s.push('x');
    }
    s.push('\n');
    s
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
            // Default: "find_iter" (consumes match spans via `m.len()`, matching rebar's count_spans)
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
