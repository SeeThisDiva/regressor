#!/usr/bin/env bash
# Verify the current tree end to end: lint, tests, and reproduction of the original study from data/.
# Compatible with both bash and POSIX sh (dash).
# Usage: bash scripts/verify.sh          (current tree)
#        bash scripts/verify.sh <git-ref> (any commit or tag, checked out into a temp dir)
# Exits non-zero if any step fails.
set -u
here="$(cd "$(dirname "$0")/.." && pwd)"
target="$here"
if [ "${1:-}" != "" ]; then
  target="$(mktemp -d)"; git -C "$here" worktree add -q --detach "$target" "$1" || exit 1
  trap 'git -C "$here" worktree remove --force "$target" 2>/dev/null || rm -rf "$target" 2>/dev/null || true' EXIT
fi
cd "$target" || exit 1

# Avoid the Windows Store "python3" alias stub.
PY=python
for cand in python python3; do
  p="$(command -v "$cand" 2>/dev/null || true)"
  case "$p" in
    ""|*WindowsApps*) continue ;;
    *) PY="$cand"; break ;;
  esac
done

status=0
echo "== tests =="
out="$("$PY" -m pytest -p no:cacheprovider 2>&1)"; rc=$?
echo "$out" | grep -E "passed|failed|error" | tail -1
[ $rc -eq 0 ] || { echo "FAIL: pytest exit $rc"; status=1; }

if command -v ruff >/dev/null && [ -f pyproject.toml ]; then
  echo "== lint =="
  out="$(ruff check . 2>&1)"; rc=$?
  echo "$out" | tail -1
  [ $rc -eq 0 ] || { echo "FAIL: ruff exit $rc"; status=1; }
fi

if [ -f data/regex_history.json.gz ]; then
  echo "== reproduction (clean DB) =="; db="$(mktemp -u).db"
  "$PY" regressor.py --db "$db" import-data data/regex_history.json.gz | tail -1
  out="$("$PY" regressor.py --db "$db" batch regex --verify-legacy 2>&1)"; rc=$?
  echo "$out" | grep -E "Total Pairwise|Post-FDR|Same flag" | sed 's/^ *//'
  [ $rc -eq 0 ] || { echo "FAIL: reproduction exit $rc"; status=1; }
  rm -f "$db"
fi

[ $status -eq 0 ] && echo "== OK ==" || echo "== FAILED =="
exit $status
