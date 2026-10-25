#!/usr/bin/env bash
set -uo pipefail
NOISE_BENCH_DIR="${NOISE_BENCH_DIR:-/work/noise-bench}"
cd "$NOISE_BENCH_DIR"
LOG=logs/batch_run.log
START=${1:-1}
COUNT=${2:-999}
total=$(wc -l < harness/commits.txt)
n=0
END=$((START + COUNT - 1))
while read -r sha; do
  n=$((n+1))
  if [ "$n" -lt "$START" ] || [ "$n" -gt "$END" ]; then continue; fi
  echo "[$n/$total] $(date -u +%H:%M:%S) starting $sha" >> "$LOG"
  python3 harness/run_commit.py "$sha" --reps 20 --iters 2000 --warmup 200 >> "$LOG" 2>&1
done < harness/commits.txt
echo "chunk ${START}-${END} done" >> "$LOG"
