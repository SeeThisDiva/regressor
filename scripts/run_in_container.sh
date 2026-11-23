#!/usr/bin/env bash
# Launch regressor inside the hardened Docker container with an explicit results bind mount,
# optional CPU pinning (--cpuset), optional offline mode (--network none + CARGO_NET_OFFLINE=true),
# and zero host credential mounts.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

IMAGE="regressor:latest"
DOCKERFILE="$REPO_ROOT/Dockerfile"
RESULTS_DIR="$REPO_ROOT/results"
DO_BUILD=0
OFFLINE=0
CPUSET=""
REGEX_SHA=""
NO_TTY=0
DRY_RUN=0
CMD_ARGS=()

usage() {
  cat <<'EOF'
Usage: scripts/run_in_container.sh [options] [-- <command...>]

Options:
  --build              Build the Docker image before running
  --image NAME         Docker image tag (default: regressor:latest)
  --dockerfile PATH    Dockerfile path (default: <repo>/Dockerfile)
  --regex-sha SHA      Override REGEX_SHA build arg when --build is set
  --results-dir DIR    Host directory mounted to /work/regressor/noise-bench/results
                       (default: <repo>/results)
  --offline            Run with `--network none` and `CARGO_NET_OFFLINE=true`
  --cpuset CPUS        Pin container to host CPU cores, e.g. 2,3 or 2-3
  --no-tty             Do not allocate a pseudo-TTY (recommended in CI)
  --dry-run            Print Docker commands without running them
  -h, --help           Show this help and exit

Examples:
  # Build image and drop into an interactive shell
  ./scripts/run_in_container.sh --build

  # Run an offline interleaved comparison pinned to cores 2 and 3
  ./scripts/run_in_container.sh --offline --cpuset 2,3 -- \
    python3 regressor.py compare-interleaved --adapter RegexAdapter \
      --repo /work/regressor/regex --base 4733e28 --cand 3d79fe9 --pairs 12

  # Run incremental upstream collection inside the container (network enabled)
  ./scripts/run_in_container.sh --no-tty -- \
    python3 scripts/continuous_collect.py --dataset auto --out-dataset noise-bench/results/updated.json.gz
EOF
}

validate_cpuset() {
  local cpus="$1"
  if [[ ! "$cpus" =~ ^[0-9]+([,-][0-9]+)*$ ]]; then
    echo "Error: invalid --cpuset value '$cpus' (expected e.g. 2,3 or 0-3)" >&2
    exit 2
  fi
}

validate_sha() {
  local sha="$1"
  if [[ -z "$sha" ]] || [[ "$sha" == -* ]] || [[ ! "$sha" =~ ^[A-Za-z0-9._/~^-]+$ ]]; then
    echo "Error: invalid --regex-sha value '$sha'" >&2
    exit 2
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --build)
      DO_BUILD=1
      shift
      ;;
    --image)
      [ "$#" -ge 2 ] || { echo "Error: --image requires a value" >&2; exit 2; }
      IMAGE="$2"
      shift 2
      ;;
    --dockerfile)
      [ "$#" -ge 2 ] || { echo "Error: --dockerfile requires a value" >&2; exit 2; }
      DOCKERFILE="$2"
      shift 2
      ;;
    --regex-sha)
      [ "$#" -ge 2 ] || { echo "Error: --regex-sha requires a value" >&2; exit 2; }
      validate_sha "$2"
      REGEX_SHA="$2"
      shift 2
      ;;
    --results-dir)
      [ "$#" -ge 2 ] || { echo "Error: --results-dir requires a value" >&2; exit 2; }
      RESULTS_DIR="$2"
      shift 2
      ;;
    --offline)
      OFFLINE=1
      shift
      ;;
    --cpuset)
      [ "$#" -ge 2 ] || { echo "Error: --cpuset requires a value" >&2; exit 2; }
      validate_cpuset "$2"
      CPUSET="$2"
      shift 2
      ;;
    --no-tty)
      NO_TTY=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --)
      shift
      CMD_ARGS=("$@")
      break
      ;;
    *)
      echo "Error: unknown option '$1' (pass '--' before container commands)" >&2
      exit 2
      ;;
  esac
done

if [ "$DRY_RUN" -eq 0 ] && ! command -v docker >/dev/null 2>&1; then
  echo "Error: 'docker' binary not found on PATH." >&2
  exit 1
fi

run_or_echo() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '%q ' "$@"
    printf '\n'
  else
    "$@"
  fi
}

if [ "$DO_BUILD" -eq 1 ]; then
  build_cmd=(docker build -t "$IMAGE" -f "$DOCKERFILE")
  if [ -n "$REGEX_SHA" ]; then
    build_cmd+=(--build-arg "REGEX_SHA=$REGEX_SHA")
  fi
  build_cmd+=("$REPO_ROOT")
  run_or_echo "${build_cmd[@]}"
fi

if [ "$DRY_RUN" -eq 0 ]; then
  mkdir -p "$RESULTS_DIR"
  RESULTS_ABS="$(cd "$RESULTS_DIR" && pwd)"
else
  RESULTS_ABS="$RESULTS_DIR"
fi

run_cmd=(
  docker run --rm --init
  --user 10001:10001
  --security-opt no-new-privileges:true
  --cap-drop ALL
  -v "${RESULTS_ABS}:/work/regressor/noise-bench/results"
)

if [ "$OFFLINE" -eq 1 ]; then
  run_cmd+=(--network none -e CARGO_NET_OFFLINE=true -e REGRESSOR_OFFLINE=1)
fi

if [ -n "$CPUSET" ]; then
  run_cmd+=(--cpuset-cpus "$CPUSET")
fi

if [ "${#CMD_ARGS[@]}" -eq 0 ]; then
  if [ "$NO_TTY" -eq 1 ]; then
    echo "Error: --no-tty requires a command after '--'" >&2
    exit 2
  fi
  if [ -t 0 ] && [ -t 1 ]; then
    run_cmd+=(-it)
  fi
  run_cmd+=("$IMAGE")
else
  if [ "$NO_TTY" -eq 0 ] && [ -t 0 ] && [ -t 1 ]; then
    run_cmd+=(-it)
  fi
  run_cmd+=("$IMAGE" "${CMD_ARGS[@]}")
fi

run_or_echo "${run_cmd[@]}"
