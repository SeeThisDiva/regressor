use regex::Regex;
use std::hint::black_box;
use std::time::Instant;

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
fn busy_wait_ns(inject_ns: u64) {
    if inject_ns == 0 {
        return;
    }
    let t0 = Instant::now();
    while (t0.elapsed().as_nanos() as u64) < inject_ns {
        black_box(0);
    }
}

fn haystack() -> String {
    let line = "2026-08-13T10:22:31Z INFO service=auth user_id=48213 action=login \
                status=success latency_ms=42 ip=10.0.4.18\n";
    line.repeat(2000)
}

fn bench_compile(iters: u32, inject_ns: u64) -> Vec<Measurement> {
    (0..iters)
        .map(|_| {
            let c0 = read_tsc_ticks();
            let start = Instant::now();
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
            let elapsed = start.elapsed().as_nanos() as u64;
            let c1 = read_tsc_ticks();
            black_box(re);
            Measurement {
                elapsed_ns: elapsed,
                tsc_ticks: c1.saturating_sub(c0),
            }
        })
        .collect()
}

fn bench_find_all(iters: u32, inject_ns: u64) -> Vec<Measurement> {
    let re = Regex::new(r"user_id=(\d+)").unwrap();
    let hay = haystack();
    (0..iters)
        .map(|_| {
            let c0 = read_tsc_ticks();
            let start = Instant::now();
            let count = re.find_iter(black_box(&hay)).count();
            busy_wait_ns(inject_ns);
            let elapsed = start.elapsed().as_nanos() as u64;
            let c1 = read_tsc_ticks();
            black_box(count);
            Measurement {
                elapsed_ns: elapsed,
                tsc_ticks: c1.saturating_sub(c0),
            }
        })
        .collect()
}

// is_match on this haystack short-circuits almost instantly (~50ns), which is
// below Instant::now()'s own resolution/call overhead on this platform -- the
// original version was measuring the timer, not the regex. Batch BATCH calls
// per timed sample so the measured duration sits well above the noise floor.
const IS_MATCH_BATCH: u32 = 500;

fn bench_is_match(iters: u32, inject_ns: u64) -> Vec<Measurement> {
    let re = Regex::new(r"status=success").unwrap();
    let hay = haystack();
    (0..iters)
        .map(|_| {
            let c0 = read_tsc_ticks();
            let start = Instant::now();
            for _ in 0..IS_MATCH_BATCH {
                black_box(re.is_match(black_box(&hay)));
            }
            busy_wait_ns(inject_ns);
            let elapsed = start.elapsed().as_nanos() as u64;
            let c1 = read_tsc_ticks();
            Measurement {
                elapsed_ns: elapsed,
                tsc_ticks: c1.saturating_sub(c0),
            }
        })
        .collect()
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let bench_name = args.get(1).map(String::as_str).unwrap_or("find_iter_userid");
    let iters: u32 = args
        .get(2)
        .and_then(|s| s.parse().ok())
        .unwrap_or(2000);
    let warmup: u32 = args
        .get(3)
        .and_then(|s| s.parse().ok())
        .unwrap_or(200);
    // Injected synthetic overhead in nanoseconds, spun inside the timed region of
    // every sample so it experiences the same OS/CPU noise as the benchmark itself.
    let inject_ns: u64 = args
        .get(4)
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);

    let mut output_format = "raw"; // "raw" (nanos), "csv" (nanos,tsc_ticks), "json"
    for arg in args.iter().skip(5) {
        if arg == "--pmu" || arg == "--format=csv" {
            output_format = "csv";
        } else if arg == "--format=json" {
            output_format = "json";
        } else if arg.starts_with("--format=") {
            output_format = &arg[9..];
        }
    }

    // Warmup, discarded, to get past cold caches / branch predictor state.
    match bench_name {
        "compile_moderate" => {
            let _ = bench_compile(warmup, 0);
        }
        "find_iter_userid" => {
            let _ = bench_find_all(warmup, 0);
        }
        "is_match_status" => {
            let _ = bench_is_match(warmup, 0);
        }
        other => {
            eprintln!("unknown bench: {other}");
            std::process::exit(1);
        }
    }

    let samples = match bench_name {
        "compile_moderate" => bench_compile(iters, inject_ns),
        "find_iter_userid" => bench_find_all(iters, inject_ns),
        "is_match_status" => bench_is_match(iters, inject_ns),
        _ => unreachable!(),
    };

    // Print measurements according to selected format
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
            // Default "raw": one nanosecond duration per line (100% backward-compatible)
            for s in samples {
                println!("{}", s.elapsed_ns);
            }
        }
    }
}
