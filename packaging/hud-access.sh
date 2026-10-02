#!/usr/bin/env bash
# Grant (or revoke) one user read-only access to the live firewall rules, so the
# HUD / conky / `umbra status` can show the REAL firewall state without root.
#
#   sudo umbra-hud-access enable            # for the user who ran sudo
#   sudo umbra-hud-access enable --user NAME
#   sudo umbra-hud-access disable
#   sudo umbra-hud-access status
#
# (Installed as /usr/sbin/umbra-hud-access by install.sh and the .deb; from a
# repo checkout it also runs as  sudo packaging/hud-access.sh ...)
#
# What it installs: /etc/sudoers.d/umbra-hud, built from packaging/umbra-hud.sudoers.
# It allows exactly `/usr/sbin/nft list ruleset` -- nothing else.
#
# Safety: a syntax error in ANY file under /etc/sudoers.d can break sudo for the
# whole machine. So the file is written to a temp path, checked with
# `visudo -cf`, and only then moved into place. A file that fails the check is
# never installed.
set -euo pipefail

DEST=/etc/sudoers.d/umbra-hud
SRC="$(cd "$(dirname "$0")" && pwd)"
# Repo checkout: the template sits next to this script. Installed: it lives in
# /usr/share/umbra (this script is in /usr/sbin, where data files don't belong).
TEMPLATE="$SRC/umbra-hud.sudoers"
[ -f "$TEMPLATE" ] || TEMPLATE=/usr/share/umbra/umbra-hud.sudoers

[ "$(id -u)" -eq 0 ] || { echo "hud-access.sh must run as root (use sudo)"; exit 1; }

cmd="${1:-}"; shift || true
user="${SUDO_USER:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --user) user="${2:-}"; shift 2 ;;
    *) echo "unknown option: $1"; exit 2 ;;
  esac
done

case "$cmd" in
  enable)
    if [ -z "$user" ] || [ "$user" = "root" ]; then
      echo "can't tell which user runs the HUD; pass it: --user NAME"; exit 2
    fi
    # A username goes into a privilege file, so accept only a plain Unix name
    # (no spaces, commas, %, or other sudoers syntax) and require it to exist.
    if ! printf '%s' "$user" | grep -Eq '^[a-z_][a-z0-9_-]*$'; then
      echo "refusing unusual username: $user"; exit 2
    fi
    id "$user" >/dev/null 2>&1 || { echo "no such user: $user"; exit 2; }
    [ -x /usr/sbin/nft ] || { echo "/usr/sbin/nft not found (install nftables)"; exit 1; }
    [ -f "$TEMPLATE" ] || { echo "template missing: $TEMPLATE"; exit 1; }

    tmp="$(mktemp)"
    trap 'rm -f "$tmp"' EXIT
    sed "s/@UMBRA_USER@/$user/" "$TEMPLATE" > "$tmp"
    chmod 0440 "$tmp"
    if ! visudo -cf "$tmp" >/dev/null; then
      echo "generated rule failed visudo's check -- NOT installed:"
      visudo -cf "$tmp" || true
      exit 1
    fi
    install -o root -g root -m 0440 "$tmp" "$DEST"
    echo "enabled: $user can read the firewall rules (only 'nft list ruleset')"
    echo "test it as $user (no password prompt expected):"
    echo "  sudo -n /usr/sbin/nft list ruleset | grep umbra"
    ;;
  disable)
    rm -f "$DEST"
    echo "disabled: removed $DEST (the HUD will show firewall n/a)"
    ;;
  status)
    if [ -f "$DEST" ]; then echo "enabled:"; grep -E '^[a-z_].*NOPASSWD' "$DEST"
    else echo "disabled"; fi
    ;;
  *)
    echo "usage: sudo $(basename "$0") enable [--user NAME] | disable | status"; exit 2 ;;
esac
