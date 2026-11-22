#!/usr/bin/env bash
# Container entrypoint for regressor.
# Automatically enables Cargo offline mode when REGRESSOR_OFFLINE=1 or when the
# container runs with `--network none` (only loopback interface present).
set -euo pipefail

if [ "${REGRESSOR_OFFLINE:-0}" = "1" ]; then
  export CARGO_NET_OFFLINE=true
elif [ -z "${CARGO_NET_OFFLINE:-}" ] || [ "${CARGO_NET_OFFLINE}" = "false" ]; then
  if [ -d /sys/class/net ]; then
    has_ext=0
    for iface in /sys/class/net/*; do
      [ -e "$iface" ] || continue
      name="${iface##*/}"
      if [ "$name" != "lo" ]; then
        has_ext=1
        break
      fi
    done
    if [ "$has_ext" -eq 0 ]; then
      export CARGO_NET_OFFLINE=true
    fi
  fi
fi

if [ "$#" -eq 0 ]; then
  exec /bin/bash
fi

case "$1" in
  -*)
    exec /bin/bash "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
