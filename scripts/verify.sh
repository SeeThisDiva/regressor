#!/usr/bin/env sh
# Verify the current tree end to end: tests, lint, and reproduction of the original study from data/.
# Compatible with both bash and POSIX sh (dash).
# Usage: sh scripts/verify.sh          (current tree)
#        sh scripts/verify.sh <git-ref> (any commit or tag, checked out into a temp dir)
# Exits non-zero if any step fails.
set -u

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  echo "Usage: sh scripts/verify.sh [git-ref]"
  exit 0
fi

here="$(cd "$(dirname "$0")/.." && pwd)"
target="$here"
worktree_created=0
tmp_db_dir=""

cleanup() {
  if [ "$worktree_created" -eq 1 ]; then
    git -C "$here" worktree remove --force "$target" 2>/dev/null || rm -rf "$target" 2>/dev/null || true
  fi
  if [ -n "$tmp_db_dir" ] && [ -d "$tmp_db_dir" ]; then
    rm -rf "$tmp_db_dir" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if [ "${1:-}" != "" ]; then
  target="$(mktemp -d)" || exit 1
  git -C "$here" worktree add -q --detach "$target" "$1" || {
    rm -rf "$target" 2>/dev/null || true
    exit 1
  }
  worktree_created=1
fi
cd "$target" || exit 1

# Avoid the Windows Store "python3" alias stub.
PY=""
for cand in python python3; do
  p="$(command -v "$cand" 2>/dev/null || true)"
  case "$p" in
    ""|*WindowsApps*) continue ;;
    *) PY="$cand"; break ;;
  esac
done
if [ -z "$PY" ]; then
  echo "FAIL: no Python interpreter found on PATH" >&2
  exit 1
fi

status=0
echo "== tests =="
out="$("$PY" -m pytest -p no:cacheprovider 2>&1)"; rc=$?
if [ "$rc" -eq 0 ]; then
  echo "$out" | grep -E "passed|failed|error" | tail -1
else
  echo "$out"
  echo "FAIL: pytest exit $rc"
  status=1
fi

if command -v ruff >/dev/null 2>&1 && [ -f pyproject.toml ]; then
  echo "== lint =="
  out="$(ruff check . 2>&1)"; rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "$out" | tail -1
  else
    echo "$out"
    echo "FAIL: ruff exit $rc"
    status=1
  fi
fi

if [ -f data/regex_history.json.gz ]; then
  echo "== reproduction (clean DB) =="
  tmp_db_dir="$(mktemp -d)" || exit 1
  db="$tmp_db_dir/verify.db"
  out="$("$PY" regressor.py --db "$db" import-data data/regex_history.json.gz 2>&1)"; rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "$out"
    echo "FAIL: import-data exit $rc"
    status=1
  else
    echo "$out" | tail -1
    out="$("$PY" regressor.py --db "$db" batch regex --verify-legacy 2>&1)"; rc=$?
    if [ "$rc" -eq 0 ]; then
      echo "$out" | grep -E "Total Pairwise|Post-FDR|Same flag" | sed 's/^ *//'
    else
      echo "$out"
      echo "FAIL: reproduction exit $rc"
      status=1
    fi
  fi
fi

[ "$status" -eq 0 ] && echo "== OK ==" || echo "== FAILED =="
exit "$status"
