#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_common.sh"
if [[ "$OS" == "Darwin" ]]; then
  # queue = rate*latency + burst = 500kbit*0.4s + 4KB ≈ 30KB (matches tbf latency 400ms)
  mac_apply "bw 500Kbit/s queue 30Kbytes"
else
  linux_reset
  sudo tc qdisc add dev "$IFACE" root tbf rate 500kbit burst 32kbit latency 400ms
fi
echo "Applied 500 kbit/s rate limit on $IFACE"
