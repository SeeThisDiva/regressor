#!/usr/bin/env bash
# Collects the 4-set synthetic validation corpus for find_iter_userid.
# Improvements over the legacy script:
#   1. Measures a pilot baseline median on this machine first instead of assuming 106 us.
#   2. Interleaves baseline_A, baseline_B, inject_8pct, and inject_1pct within each rep
#      (rotating order per rep) so slow host/thermal drift hits all four sets equally.
set -euo pipefail
BIN=./target/release/noise-bench
REPS=30
ITERS=2000
WARMUP=200
OUT=validation
mkdir -p "$OUT/baseline_A" "$OUT/baseline_B" "$OUT/inject_8pct" "$OUT/inject_1pct"

BASE_NS="$(python3 - "$BIN" "$ITERS" "$WARMUP" <<'PY'
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
