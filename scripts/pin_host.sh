#!/usr/bin/env bash
# Bare-metal Linux CPU isolation and frequency-pinning helper for low-noise benchmarking.
#
# Idempotent and safe:
#   - Inspects system state by default (--status) without modifying anything.
#   - Requires explicit --apply (or --restore) and root privileges on Linux to change CPU state.
#   - Supports --dry-run on any OS to preview exact commands and isolcpus/taskset guidance.
#   - Refuses to offline CPU 0 and never modifies /etc/default/grub automatically.
set -euo pipefail

ACTION="status"
CPUS="2,3"
FREQ=""
OFFLINE_CPU=""
RESTORE_GOV="schedutil"
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: scripts/pin_host.sh [options]

Actions (default: --status):
  --status             Inspect current Linux governors, turbo/boost, isolcpus, and PMU settings
  --apply              Idempotently set performance governor and disable CPU turbo/boost
  --restore            Restore dynamic governor and re-enable CPU turbo/boost
  --dry-run            Preview commands without mutating the system (safe on any OS)

Options:
  --cpus LIST          CPU list used for taskset/isolcpus guidance (default: 2,3)
  --freq FREQ          Optional fixed clock for cpupower (e.g. 3.0GHz, 2600MHz)
  --offline-cpu N      Optional SMT sibling CPU index (>= 1) to offline under --apply
                       (and re-online under --restore)
  --governor GOV       Governor to set on --restore (default: schedutil; falls back to powersave)
  -h, --help           Show this help and exit

Kernel Boot Isolation Guidance (persistent across reboots):
  Add to GRUB_CMDLINE_LINUX_DEFAULT in /etc/default/grub, then run update-grub and reboot:
    isolcpus=2,3 nohz_full=2,3 rcu_nocbs=2,3

Running Benchmarks Pinned to an Isolated Core:
  taskset -c 2 nice -n -20 ./target/release/noise-bench find_iter_userid 2000 200
  taskset -c 2 nice -n -20 python3 regressor.py compare-interleaved --adapter RegexAdapter ...
EOF
}

validate_cpus() {
  if [[ ! "$1" =~ ^[0-9]+([,-][0-9]+)*$ ]]; then
    echo "Error: invalid --cpus '$1' (expected e.g. 2,3 or 2-3)" >&2
    exit 2
  fi
}

validate_freq() {
  if [[ ! "$1" =~ ^[0-9]+(\.[0-9]+)?(GHz|MHz|kHz|Hz)$ ]]; then
    echo "Error: invalid --freq '$1' (expected e.g. 3.0GHz or 2600MHz)" >&2
    exit 2
  fi
}

validate_cpu_index() {
  if [[ ! "$1" =~ ^[0-9]+$ ]] || [ "$1" -lt 1 ]; then
    echo "Error: --offline-cpu must be an integer >= 1 (CPU 0 cannot be offlined)" >&2
    exit 2
  fi
}

validate_governor() {
  if [[ ! "$1" =~ ^[a-z_]+$ ]]; then
    echo "Error: invalid --governor '$1'" >&2
    exit 2
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --status)
      ACTION="status"
      shift
      ;;
    --apply)
      ACTION="apply"
      shift
      ;;
    --restore)
      ACTION="restore"
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --cpus)
      [ "$#" -ge 2 ] || { echo "Error: --cpus requires a value" >&2; exit 2; }
      validate_cpus "$2"
      CPUS="$2"
      shift 2
      ;;
    --freq)
      [ "$#" -ge 2 ] || { echo "Error: --freq requires a value" >&2; exit 2; }
      validate_freq "$2"
      FREQ="$2"
      shift 2
      ;;
    --offline-cpu)
      [ "$#" -ge 2 ] || { echo "Error: --offline-cpu requires a value" >&2; exit 2; }
      validate_cpu_index "$2"
      OFFLINE_CPU="$2"
      shift 2
      ;;
    --governor)
      [ "$#" -ge 2 ] || { echo "Error: --governor requires a value" >&2; exit 2; }
      validate_governor "$2"
      RESTORE_GOV="$2"
      shift 2
      ;;
    *)
      echo "Error: unknown option '$1'" >&2
      exit 2
      ;;
  esac
done

FIRST_CPU="${CPUS%%[,-]*}"

print_guidance() {
  echo ""
  echo "== Bare-Metal Isolation & Pinning Guidance =="
  echo "  1. Persistent GRUB kernel parameters (/etc/default/grub -> GRUB_CMDLINE_LINUX_DEFAULT):"
  echo "       isolcpus=${CPUS} nohz_full=${CPUS} rcu_nocbs=${CPUS}"
  echo "     Then run: sudo update-grub && sudo reboot"
  echo "     Verify after reboot: grep -E 'isolcpus|nohz_full|rcu_nocbs' /proc/cmdline"
  echo "  2. Run pinned to core ${FIRST_CPU} at high scheduling priority:"
  echo "       taskset -c ${FIRST_CPU} nice -n -20 ./noise-bench/target/release/noise-bench find_iter_userid 2000 200"
  echo "       taskset -c ${FIRST_CPU} nice -n -20 python3 regressor.py compare-interleaved --adapter RegexAdapter --repo regex --base <shaA> --cand <shaB>"
  echo "  3. Verify baseline CV < 10.5% before historical sweeps (see SETUP.md)."
}

show_status() {
  local os
  os="$(uname -s 2>/dev/null || echo unknown)"
  echo "== Host CPU Isolation Status (OS: ${os}) =="
  if [ "$os" != "Linux" ]; then
    echo "  Non-Linux host detected; Linux sysfs/cpupower controls are unavailable here."
    print_guidance
    return 0
  fi

  if [ -r /proc/cmdline ]; then
    local cmdline
    cmdline="$(cat /proc/cmdline)"
    if echo "$cmdline" | grep -q "isolcpus="; then
      echo "  /proc/cmdline isolcpus: $(echo "$cmdline" | tr ' ' '\n' | grep -E '^(isolcpus|nohz_full|rcu_nocbs)=' | tr '\n' ' ')"
    else
      echo "  /proc/cmdline isolcpus: NOT SET (recommended: isolcpus=${CPUS} nohz_full=${CPUS} rcu_nocbs=${CPUS})"
    fi
  fi

  local gov_files=(/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor)
  if [ -r "${gov_files[0]}" ]; then
    echo "  Scaling governors: $(sort -u "${gov_files[@]}" | tr '\n' ' ')"
  else
    echo "  Scaling governors: unavailable (VM or no cpufreq driver)"
  fi

  if [ -r /sys/devices/system/cpu/intel_pstate/no_turbo ]; then
    echo "  Intel no_turbo: $(cat /sys/devices/system/cpu/intel_pstate/no_turbo) (1 = turbo disabled)"
  elif [ -r /sys/devices/system/cpu/cpufreq/boost ]; then
    echo "  AMD/cpufreq boost: $(cat /sys/devices/system/cpu/cpufreq/boost) (0 = turbo disabled)"
  else
    echo "  Turbo/boost sysfs: unavailable"
  fi

  if [ -r /proc/sys/kernel/perf_event_paranoid ]; then
    echo "  kernel.perf_event_paranoid: $(cat /proc/sys/kernel/perf_event_paranoid)"
  fi

  if [ -n "$OFFLINE_CPU" ] && [ -r "/sys/devices/system/cpu/cpu${OFFLINE_CPU}/online" ]; then
    echo "  cpu${OFFLINE_CPU} online: $(cat "/sys/devices/system/cpu/cpu${OFFLINE_CPU}/online")"
  fi

  print_guidance
}

write_sysfs_if_needed() {
  local target="$1"
  local value="$2"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "[dry-run] echo ${value} > ${target}"
    return 0
  fi
  if [ ! -e "$target" ]; then
    return 1
  fi
  local current=""
  current="$(cat "$target" 2>/dev/null || true)"
  if [ "$current" = "$value" ]; then
    echo "  [unchanged] ${target} already '${value}'"
    return 0
  fi
  printf '%s\n' "$value" > "$target"
  echo "  [updated]   ${target} -> '${value}'"
}

set_governor() {
  local gov="$1"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "[dry-run] cpupower frequency-set -g ${gov}  # (or write ${gov} to scaling_governor)"
    return 0
  fi
  if command -v cpupower >/dev/null 2>&1; then
    cpupower frequency-set -g "$gov" >/dev/null
    echo "  [updated]   cpupower governor -> '${gov}'"
  else
    local updated=0
    for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
      [ -w "$f" ] || continue
      write_sysfs_if_needed "$f" "$gov"
      updated=1
    done
    if [ "$updated" -eq 0 ]; then
      echo "  [skipped]   neither cpupower nor writable scaling_governor found"
    fi
  fi
}

require_linux_root_unless_dry_run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    return 0
  fi
  if [ "$(uname -s 2>/dev/null || echo unknown)" != "Linux" ]; then
    echo "Error: --${ACTION} only runs on bare-metal Linux (use --dry-run to preview commands)." >&2
    exit 1
  fi
  if [ "$(id -u)" -ne 0 ]; then
    echo "Error: --${ACTION} requires root privileges. Re-run with sudo." >&2
    exit 1
  fi
}

apply_pinning() {
  require_linux_root_unless_dry_run
  echo "== Applying Low-Noise CPU Settings =="
  set_governor "performance"

  if [ -n "$FREQ" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "[dry-run] cpupower frequency-set -d ${FREQ} -u ${FREQ}"
    elif command -v cpupower >/dev/null 2>&1; then
      cpupower frequency-set -d "$FREQ" -u "$FREQ" >/dev/null
      echo "  [updated]   cpupower frequency pinned to ${FREQ}"
    else
      echo "  [warning]   cpupower not installed; skipping --freq ${FREQ}" >&2
    fi
  fi

  if [ "$DRY_RUN" -eq 1 ] || [ -e /sys/devices/system/cpu/intel_pstate/no_turbo ]; then
    write_sysfs_if_needed /sys/devices/system/cpu/intel_pstate/no_turbo "1" || true
  fi
  if [ "$DRY_RUN" -eq 1 ] || [ -e /sys/devices/system/cpu/cpufreq/boost ]; then
    write_sysfs_if_needed /sys/devices/system/cpu/cpufreq/boost "0" || true
  fi

  if [ -n "$OFFLINE_CPU" ]; then
    local online_path="/sys/devices/system/cpu/cpu${OFFLINE_CPU}/online"
    if [ "$DRY_RUN" -eq 1 ] || [ -e "$online_path" ]; then
      write_sysfs_if_needed "$online_path" "0" || true
    else
      echo "  [skipped]   ${online_path} does not exist"
    fi
  fi

  print_guidance
}

restore_defaults() {
  require_linux_root_unless_dry_run
  echo "== Restoring Dynamic CPU Settings =="

  local target_gov="$RESTORE_GOV"
  if [ "$DRY_RUN" -eq 0 ] && [ -r /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors ]; then
    local avail
    avail="$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors)"
    if [[ " $avail " != *" $target_gov "* ]] && [[ " $avail " == *" powersave "* ]]; then
      target_gov="powersave"
    fi
  fi
  set_governor "$target_gov"

  if [ "$DRY_RUN" -eq 1 ] || [ -e /sys/devices/system/cpu/intel_pstate/no_turbo ]; then
    write_sysfs_if_needed /sys/devices/system/cpu/intel_pstate/no_turbo "0" || true
  fi
  if [ "$DRY_RUN" -eq 1 ] || [ -e /sys/devices/system/cpu/cpufreq/boost ]; then
    write_sysfs_if_needed /sys/devices/system/cpu/cpufreq/boost "1" || true
  fi

  if [ -n "$OFFLINE_CPU" ]; then
    local online_path="/sys/devices/system/cpu/cpu${OFFLINE_CPU}/online"
    if [ "$DRY_RUN" -eq 1 ] || [ -e "$online_path" ]; then
      write_sysfs_if_needed "$online_path" "1" || true
    fi
  fi
}

case "$ACTION" in
  status)
    show_status
    ;;
  apply)
    apply_pinning
    ;;
  restore)
    restore_defaults
    ;;
esac
