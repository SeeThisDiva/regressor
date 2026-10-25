import glob
import statistics

outdir = sorted(glob.glob("results/*_baseline"))[-1]
benches = ["compile_moderate", "find_iter_userid", "is_match_status"]

print(f"Analyzing: {outdir}\n")

for bench in benches:
    files = sorted(glob.glob(f"{outdir}/{bench}_rep*.txt"))
    assert len(files) == 50, f"expected 50 reps, got {len(files)}"

    run_medians = []
    all_within_run_p99_over_p50 = []
    for f in files:
        vals = [int(x) for x in open(f)]
        vals.sort()
        n = len(vals)
        med = vals[n // 2]
        p99 = vals[int(n * 0.99)]
        run_medians.append(med)
        all_within_run_p99_over_p50.append(p99 / med)

    mean_ = statistics.mean(run_medians)
    stdev_ = statistics.stdev(run_medians)
    cv = 100 * stdev_ / mean_
    lo, hi = min(run_medians), max(run_medians)

    print(f"=== {bench} ===")
    print(f"  across 50 runs, each run's median of 2000 iters (ns):")
    print(f"    mean={mean_:,.0f}  stdev={stdev_:,.0f}  CV={cv:.2f}%")
    print(f"    min={lo:,}  max={hi:,}  max/min={hi/lo:.2f}x")
    print(f"  within a single run, p99/p50 ratio (tail heaviness):")
    print(f"    mean={statistics.mean(all_within_run_p99_over_p50):.2f}x  "
          f"worst={max(all_within_run_p99_over_p50):.2f}x")
    print()
