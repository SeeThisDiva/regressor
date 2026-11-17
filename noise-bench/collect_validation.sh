#!/usr/bin/env bash
# Collect the 4-set synthetic validation corpus for `find_iter_userid`.
#
# 1. Measures a 3-rep pilot baseline median (`BASE_NS`) on the current machine
#    to calibrate +8% and +1% synthetic slowdowns dynamically.
# 2. Interleaves `baseline_A`, `baseline_B`, `inject_8pct`, and `inject_1pct`
#    within each rep (rotating order per rep) so slow host/thermal drift hits
#    all four sets equally.
set -euo pipefail

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  echo "Usage: $0"
  echo "Runs 30 interleaved reps of find_iter_userid across baseline_A/B and +8%/+1% synthetic slowdowns."
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

REPS=30
ITERS=2000
WARMUP=200
OUT=validation
mkdir -p "$OUT/baseline_A" "$OUT/baseline_B" "$OUT/inject_8pct" "$OUT/inject_1pct"

BASE_NS="$("$PY" - "$BIN" "$ITERS" "$WARMUP" <<'PY'
import subprocess, sys, numpy as np
bin_path, iters, warmup = sys.argv[1], sys.argv[2], sys.argv[3]
meds = []
for _ in range(3):
    out = subprocess.check_output([bin_path, "find_iter_userid", iters, warmup, "0"], text=True)
    meds.append(float(np.median([float(x) for x in out.split()])))
print(int(round(float(np.median(meds)))))
PY
)"

INJ_8PCT=$(( (BASE_NS * 8 + 50) / 100 ))
INJ_1PCT=$(( (BASE_NS * 1 + 50) / 100 ))
echo "pilot median: ${BASE_NS} ns -> inject_8pct=${INJ_8PCT} ns, inject_1pct=${INJ_1PCT} ns"

LABELS=(baseline_A baseline_B inject_8pct inject_1pct)
INJECTS=(0 0 "$INJ_8PCT" "$INJ_1PCT")

for idx in $(seq 1 "$REPS"); do
  rep=$(printf "%02d" "$idx")
  for k in 0 1 2 3; do
    slot=$(( (idx + k) % 4 ))
    label="${LABELS[$slot]}"
    inj="${INJECTS[$slot]}"
    "$BIN" find_iter_userid "$ITERS" "$WARMUP" "$inj" > "$OUT/$label/rep${rep}.txt"
  done
done
echo "done: collected $REPS interleaved reps across ${LABELS[*]}"
