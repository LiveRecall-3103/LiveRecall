# Shared helpers: Linux uses tc/netem, macOS uses dnctl (dummynet) + pfctl.
OS="$(uname -s)"
IFACE="${1:-lo}"
if [[ "$OS" == "Darwin" && "$IFACE" == "lo" ]]; then IFACE="lo0"; fi
MAC_ANCHOR="com.apple/liverecall"   # com.apple/* is already a dummynet-anchor in default /etc/pf.conf

# mac_apply "<dnctl pipe config args>"   e.g. mac_apply "delay 120 plr 0.03"
mac_apply() {
  mac_reset
  sudo dnctl pipe 1 config $1
  # 'out' only: on loopback every packet goes out lo0 once, so shaping is applied once per packet.
  echo "dummynet out quick on $IFACE all pipe 1" | sudo pfctl -q -a "$MAC_ANCHOR" -f -
  sudo pfctl -q -E 2>/dev/null || true
}

mac_reset() {
  sudo pfctl -q -a "$MAC_ANCHOR" -F all 2>/dev/null || true
  sudo dnctl -q flush 2>/dev/null || true
}

linux_reset() { sudo tc qdisc del dev "$IFACE" root 2>/dev/null || true; }
