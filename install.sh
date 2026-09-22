#!/usr/bin/env bash
# Umbra installer for Debian/Kali. Idempotent: safe to re-run.
#
#   sudo ./install.sh                     # install umbra as a system command
#   sudo ./install.sh --with-boot-service # also apply a posture at every boot
#
# Layout it creates:
#   /opt/umbra/{umbra,profiles,schema}    the code + data
#   /usr/local/bin/umbra                  a thin wrapper -> python3 -m umbra.cli
#   /etc/umbra/boot-profile               (with --with-boot-service) the profile name
#   /etc/systemd/system/umbra-boot.service
set -euo pipefail

PREFIX=/opt/umbra
BIN=/usr/local/bin/umbra
SRC="$(cd "$(dirname "$0")" && pwd)"

[ "$(id -u)" -eq 0 ] || { echo "install.sh must run as root (use sudo)"; exit 1; }

echo "[1/4] dependencies"
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -y >/dev/null
  # Use distro packages (avoids PEP 668 'externally managed' pip friction).
  apt-get install -y python3 python3-yaml python3-jsonschema nftables >/dev/null
else
  echo "  (no apt-get; ensure python3 + PyYAML + jsonschema + nftables are present)"
fi

echo "[2/4] install code -> $PREFIX"
rm -rf "$PREFIX"
mkdir -p "$PREFIX"
cp -r "$SRC/umbra" "$SRC/profiles" "$SRC/schema" "$PREFIX/"
find "$PREFIX" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
# World-readable so a non-root user can run `umbra` (needed for `umbra --pkexec`,
# which starts as that user before elevating). A restrictive umask (027) would
# otherwise leave /opt/umbra root-only.
chmod -R a+rX "$PREFIX"

echo "[3/4] wrapper -> $BIN"
cat > "$BIN" <<EOF
#!/bin/sh
# umbra launcher (installed by install.sh)
exec /usr/bin/env PYTHONPATH="$PREFIX" python3 -m umbra.cli "\$@"
EOF
chmod 0755 "$BIN"
# umbra is a root tool, almost always run as `sudo umbra ...`. On some images
# sudo's secure_path excludes /usr/local/bin, so also expose it under /usr/sbin
# (which is in secure_path) via a symlink, so `sudo umbra` always resolves.
ln -sf "$BIN" /usr/sbin/umbra
# /usr/bin/umbra so the polkit action's exec.path resolves for `umbra --pkexec`.
ln -sf "$BIN" /usr/bin/umbra

# man page (best-effort)
if [ -f "$SRC/packaging/umbra.1" ] && [ -d /usr/share/man/man1 ]; then
  cp "$SRC/packaging/umbra.1" /usr/share/man/man1/umbra.1
  command -v mandb >/dev/null 2>&1 && mandb -q >/dev/null 2>&1 || true
fi

# polkit policy (desktop auth for posture changes via `umbra --pkexec`)
if [ -d /usr/share/polkit-1/actions ]; then
  cp "$SRC/packaging/com.forrestlasiter.umbra.policy" /usr/share/polkit-1/actions/
  # 644 so polkitd (which may run as an unprivileged 'polkitd' user) can read it.
  chmod 0644 /usr/share/polkit-1/actions/com.forrestlasiter.umbra.policy
fi

# NetworkManager dispatcher: re-assert the active posture on network change.
if [ -d /etc/NetworkManager/dispatcher.d ]; then
  cp "$SRC/packaging/umbra-nm-dispatcher" /etc/NetworkManager/dispatcher.d/50-umbra
  chown root:root /etc/NetworkManager/dispatcher.d/50-umbra 2>/dev/null || true
  chmod 0755 /etc/NetworkManager/dispatcher.d/50-umbra
fi

# desktop launcher for the tray toggle
if [ -d /usr/share/applications ]; then
  cp "$SRC/packaging/umbra-tray.desktop" /usr/share/applications/umbra-tray.desktop
  chmod 0644 /usr/share/applications/umbra-tray.desktop
fi

echo "[4/4] boot service"
if [ "${1:-}" = "--with-boot-service" ]; then
  mkdir -p /etc/umbra
  [ -f /etc/umbra/boot-profile ] || echo "home" > /etc/umbra/boot-profile
  cp "$SRC/packaging/umbra-boot.service" /etc/systemd/system/umbra-boot.service
  systemctl daemon-reload
  systemctl enable umbra-boot.service >/dev/null
  echo "  enabled: applies /etc/umbra/boot-profile ('$(cat /etc/umbra/boot-profile)') at boot"
else
  echo "  skipped (pass --with-boot-service to enable go-dark-at-boot)"
fi

echo
echo "installed. try:  umbra status home"
echo "uninstall with:  sudo $SRC/uninstall.sh"
