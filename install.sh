#!/usr/bin/env bash
# Umbra installer for Debian/Kali. Idempotent: safe to re-run.
#
#   sudo ./install.sh                     # install umbra as a system command
#   sudo ./install.sh --with-boot-service # also apply a posture at every boot
#   sudo ./install.sh --with-hud-access   # let YOUR user read the firewall rules,
#                                         # so the HUD shows the real firewall state
#   (flags combine:  sudo ./install.sh --with-boot-service --with-hud-access)
#
# Layout it creates:
#   /opt/umbra/{umbra,profiles,schema}    the code + data
#   /usr/local/bin/umbra                  a thin wrapper -> python3 -m umbra.cli
#   /etc/umbra/boot-profile               (with --with-boot-service) the profile name
#   /etc/systemd/system/umbra-boot.service
#   /usr/sbin/umbra-hud-access            grant/revoke HUD firewall-read access
#   /usr/share/umbra/umbra-hud.sudoers    the rule template it installs
set -euo pipefail

PREFIX=/opt/umbra
BIN=/usr/local/bin/umbra
SRC="$(cd "$(dirname "$0")" && pwd)"

[ "$(id -u)" -eq 0 ] || { echo "install.sh must run as root (use sudo)"; exit 1; }

WITH_BOOT=0
WITH_HUD_ACCESS=0
for arg in "$@"; do
  case "$arg" in
    --with-boot-service) WITH_BOOT=1 ;;
    --with-hud-access)   WITH_HUD_ACCESS=1 ;;
    *) echo "unknown option: $arg"; exit 2 ;;
  esac
done

echo "[1/5] dependencies"
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -y >/dev/null
  # Use distro packages (avoids PEP 668 'externally managed' pip friction).
  apt-get install -y python3 python3-yaml python3-jsonschema nftables >/dev/null
else
  echo "  (no apt-get; ensure python3 + PyYAML + jsonschema + nftables are present)"
fi

echo "[2/5] install code -> $PREFIX"
rm -rf "$PREFIX"
mkdir -p "$PREFIX"
# profiles/ and schema/ ship inside the umbra package now, so this is all we copy.
cp -r "$SRC/umbra" "$PREFIX/"
find "$PREFIX" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
# World-readable so a non-root user can run `umbra` (needed for `umbra --pkexec`,
# which starts as that user before elevating). A restrictive umask (027) would
# otherwise leave /opt/umbra root-only.
chmod -R a+rX "$PREFIX"

echo "[3/5] wrapper -> $BIN"
cat > "$BIN" <<EOF
#!/bin/sh
# umbra launcher (installed by install.sh). Absolute interpreter path.
exec /usr/bin/env PYTHONPATH="$PREFIX" /usr/bin/python3 -m umbra.cli "\$@"
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

# desktop launchers for the tray toggle and the Ops HUD (both launch detached,
# no terminal — click them from the app menu)
if [ -d /usr/share/applications ]; then
  cp "$SRC/packaging/umbra-tray.desktop" /usr/share/applications/umbra-tray.desktop
  cp "$SRC/packaging/umbra-hud.desktop" /usr/share/applications/umbra-hud.desktop
  chmod 0644 /usr/share/applications/umbra-tray.desktop /usr/share/applications/umbra-hud.desktop
fi

# HUD firewall-read access helper (opt-in; does nothing until you run it)
install -o root -g root -m 0755 "$SRC/packaging/hud-access.sh" /usr/sbin/umbra-hud-access
mkdir -p /usr/share/umbra
install -o root -g root -m 0644 "$SRC/packaging/umbra-hud.sudoers" /usr/share/umbra/umbra-hud.sudoers

# systemd --user unit so the HUD comes up on login and restarts if it dies.
# Enable it per-user (NOT as root):  systemctl --user enable --now umbra-hud
if [ -d /usr/lib/systemd/user ]; then
  cp "$SRC/packaging/umbra-hud.service" /usr/lib/systemd/user/umbra-hud.service
  chmod 0644 /usr/lib/systemd/user/umbra-hud.service
fi

echo "[4/5] boot service"
if [ "$WITH_BOOT" -eq 1 ]; then
  mkdir -p /etc/umbra
  [ -f /etc/umbra/boot-profile ] || echo "home" > /etc/umbra/boot-profile
  cp "$SRC/packaging/umbra-boot.service" /etc/systemd/system/umbra-boot.service
  systemctl daemon-reload
  systemctl enable umbra-boot.service >/dev/null
  echo "  enabled: applies /etc/umbra/boot-profile ('$(cat /etc/umbra/boot-profile)') at boot"
else
  echo "  skipped (pass --with-boot-service to enable go-dark-at-boot)"
fi

echo "[5/5] HUD firewall access"
if [ "$WITH_HUD_ACCESS" -eq 1 ]; then
  /usr/sbin/umbra-hud-access enable
else
  echo "  skipped (the HUD shows firewall n/a without it; enable later with:"
  echo "           sudo umbra-hud-access enable)"
fi

echo
echo "installed. try:  umbra status home"
echo "always-on HUD:   systemctl --user enable --now umbra-hud   (or launch 'Umbra HUD' from the menu)"
echo "uninstall with:  sudo $SRC/uninstall.sh"
