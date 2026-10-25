#!/usr/bin/env bash
# Phase 1 noise study: run each benchmark 50 times as separate process
# invocations of the SAME binary (same commit, same code) and record
# every inner-iteration timing. Outer repetition count is what matters
# for change-point detection later: in real use we re-run the whole
# benchmark per commit, not just one process.
set -euo pipefail

BIN=./target/release/noise-bench
OUTDIR=results/$(date +%Y%m%dT%H%M%S)_baseline
mkdir -p "$OUTDIR"

BENCHES=(compile_moderate find_iter_userid is_match_status)
REPS=50
ITERS=2000
WARMUP=200

for bench in "${BENCHES[@]}"; do
  for rep in $(seq -w 1 "$REPS"); do
    "$BIN" "$bench" "$ITERS" "$WARMUP" > "$OUTDIR/${bench}_rep${rep}.txt"
  done
  echo "done: $bench ($REPS reps x $ITERS iters)"
done

echo "results in $OUTDIR"
