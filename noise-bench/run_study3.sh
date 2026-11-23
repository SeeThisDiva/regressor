#!/usr/bin/env sh
# Resumable Study 3 sweep wrapper: delegates to harness/run_study3.py.
# Compatible with POSIX sh / bash on Windows Git Bash and Linux/container hosts.
set -u

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  echo "Usage: sh noise-bench/run_study3.sh [run_study3.py args...]"
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

PY=""
for cand in python python3; do
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

cd "$SCRIPT_DIR" || exit 1
exec "$PY" harness/run_study3.py "$@"
