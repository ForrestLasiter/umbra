#!/usr/bin/env bash
# Remove umbra. Restores any active posture FIRST, so uninstalling can never
# leave the machine stuck in a hardened/dark state.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "uninstall.sh must run as root (use sudo)"; exit 1; }

echo "[1/4] restore any active posture to stock"
if [ -x /usr/local/bin/umbra ]; then
  /usr/local/bin/umbra normal || echo "  (nothing to restore, or restore reported issues)"
fi

echo "[2/4] remove boot service"
systemctl disable --now umbra-boot.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/umbra-boot.service
systemctl daemon-reload >/dev/null 2>&1 || true

echo "[3/4] remove code + wrapper"
rm -f /usr/local/bin/umbra /usr/sbin/umbra /usr/bin/umbra
rm -f /usr/share/man/man1/umbra.1
rm -f /usr/share/polkit-1/actions/com.forrestlasiter.umbra.policy
rm -rf /opt/umbra

echo "[4/4] leaving /etc/umbra and /var/lib/umbra (config + snapshots) intact"
echo "  remove them manually if you want a clean slate:"
echo "    sudo rm -rf /etc/umbra /var/lib/umbra"
echo
echo "umbra uninstalled."
