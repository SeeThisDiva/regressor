#!/usr/bin/env bash
# Baseline noise-floor calibration study: run each benchmark REPS times as
# separate process invocations of the SAME binary (same commit, same code) and
# record every inner-iteration timing. Cross-process variance is the relevant
# unit for change-point detection across commits.
set -euo pipefail

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  echo "Usage: $0"
  echo "Env overrides: REPS=50 ITERS=2000 WARMUP=200"
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BIN=./target/release/noise-bench
if [ ! -x "$BIN" ] && [ -x "${BIN}.exe" ]; then
  BIN="${BIN}.exe"
fi
if [ ! -x "$BIN" ]; then
  echo "Error: noise-bench binary not found at $BIN (build first: cargo build --release)" >&2
  exit 1
fi

OUTDIR="results/$(date +%Y%m%dT%H%M%S)_baseline"
mkdir -p "$OUTDIR"

BENCHES=(compile_moderate find_iter_userid is_match_status)
REPS="${REPS:-50}"
ITERS="${ITERS:-2000}"
WARMUP="${WARMUP:-200}"

for bench in "${BENCHES[@]}"; do
  for rep in $(seq -w 1 "$REPS"); do
    "$BIN" "$bench" "$ITERS" "$WARMUP" > "$OUTDIR/${bench}_rep${rep}.txt"
  done
  echo "done: $bench ($REPS reps x $ITERS iters)"
done

echo "results in $OUTDIR"
