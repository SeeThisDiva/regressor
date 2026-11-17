#!/usr/bin/env bash
# Sweep commits in harness/commits.txt sequentially via harness/run_commit.py.
# Usage: ./run_batch.sh [start_index] [count]
# Env:   NOISE_BENCH_DIR (defaults to /work/regressor/noise-bench in container, else script dir)
#        REGEX_REPO      (defaults to /work/regressor/regex in container, else ../regex)
set -uo pipefail

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  echo "Usage: $0 [start_index] [count]"
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -z "${NOISE_BENCH_DIR:-}" ]; then
  if [ -d "/work/regressor/noise-bench" ]; then
    NOISE_BENCH_DIR="/work/regressor/noise-bench"
  else
    NOISE_BENCH_DIR="$SCRIPT_DIR"
  fi
fi
export NOISE_BENCH_DIR

if [ -z "${REGEX_REPO:-}" ]; then
  if [ "$NOISE_BENCH_DIR" = "/work/regressor/noise-bench" ]; then
    REGEX_REPO="/work/regressor/regex"
  else
    REGEX_REPO="$(dirname "$NOISE_BENCH_DIR")/regex"
  fi
fi
export REGEX_REPO

PY=""
for cand in python3 python; do
  p="$(command -v "$cand" 2>/dev/null || true)"
  case "$p" in
    ""|*WindowsApps*) continue ;;
    *) PY="$cand"; break ;;
  esac
done
if [ -z "$PY" ]; then
  echo "Error: Python interpreter not found on PATH" >&2
  exit 1
fi

cd "$NOISE_BENCH_DIR" || exit 1
LOG=logs/batch_run.log
mkdir -p "$(dirname "$LOG")"
START=${1:-1}
COUNT=${2:-999}
total=$(wc -l < harness/commits.txt)
n=0
END=$((START + COUNT - 1))
while IFS= read -r sha || [ -n "$sha" ]; do
  [ -z "$sha" ] && continue
  n=$((n+1))
  if [ "$n" -lt "$START" ] || [ "$n" -gt "$END" ]; then continue; fi
  echo "[$n/$total] $(date -u +%H:%M:%S) starting $sha" >> "$LOG"
  "$PY" harness/run_commit.py "$sha" --reps 20 --iters 2000 --warmup 200 >> "$LOG" 2>&1
done < harness/commits.txt
echo "chunk ${START}-${END} done" >> "$LOG"
