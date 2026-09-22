#!/usr/bin/env bash
# Build a Debian package for umbra. Run on a Debian/Kali box (needs dpkg-deb).
#
#   packaging/build-deb.sh          -> dist/umbra_<version>_all.deb
#
# The .deb layout (distinct from install.sh's /opt layout):
#   /usr/lib/umbra/{umbra,profiles,schema}   code + data
#   /usr/bin/umbra                           wrapper (in PATH and sudo secure_path)
#   /usr/share/man/man1/umbra.1              man page
#   /lib/systemd/system/umbra-boot.service   boot service (disabled by default)
#   /etc/umbra/boot-profile                  conffile (preserves user edits)
set -euo pipefail

VERSION=0.1.0
ARCH=all
SRC="$(cd "$(dirname "$0")/.." && pwd)"          # repo root
STAGE="$(mktemp -d)/umbra_${VERSION}_${ARCH}"

mkdir -p "$STAGE/DEBIAN" \
         "$STAGE/usr/lib/umbra" \
         "$STAGE/usr/bin" \
         "$STAGE/usr/share/man/man1" \
         "$STAGE/usr/share/polkit-1/actions" \
         "$STAGE/usr/share/applications" \
         "$STAGE/etc/NetworkManager/dispatcher.d" \
         "$STAGE/lib/systemd/system" \
         "$STAGE/etc/umbra"

# code + data
cp -r "$SRC/umbra" "$SRC/profiles" "$SRC/schema" "$STAGE/usr/lib/umbra/"
find "$STAGE/usr/lib/umbra" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

# wrapper (PYTHONPATH points at the packaged code root)
cat > "$STAGE/usr/bin/umbra" <<'EOF'
#!/bin/sh
exec /usr/bin/env PYTHONPATH=/usr/lib/umbra /usr/bin/python3 -m umbra.cli "$@"
EOF
chmod 0755 "$STAGE/usr/bin/umbra"

cp "$SRC/packaging/umbra.1" "$STAGE/usr/share/man/man1/umbra.1"
cp "$SRC/packaging/com.forrestlasiter.umbra.policy" "$STAGE/usr/share/polkit-1/actions/"
cp "$SRC/packaging/umbra-nm-dispatcher" "$STAGE/etc/NetworkManager/dispatcher.d/50-umbra"
cp "$SRC/packaging/umbra-tray.desktop" "$STAGE/usr/share/applications/umbra-tray.desktop"
cp "$SRC/packaging/umbra-boot.service" "$STAGE/lib/systemd/system/umbra-boot.service"
echo home > "$STAGE/etc/umbra/boot-profile"

cat > "$STAGE/DEBIAN/control" <<EOF
Package: umbra
Version: $VERSION
Section: admin
Priority: optional
Architecture: $ARCH
Depends: python3, python3-yaml, python3-jsonschema, nftables
Recommends: python3-gi, gir1.2-ayatanaappindicator3-0.1, policykit-1
Maintainer: Forrest Lasiter <forrest.lasiter@gmail.com>
Description: One-toggle privacy/anonymity/hardening posture engine
 Umbra reconciles a Linux machine to a declarative privacy posture (a profile)
 and can restore it exactly. Every change is snapshotted before it is applied,
 so any posture can be cleanly undone, even after a crash.
EOF

echo "/etc/umbra/boot-profile" > "$STAGE/DEBIAN/conffiles"

# prerm: restore posture to stock BEFORE the package is removed, so uninstalling
# can never strand the machine in a hardened/dark state.
cat > "$STAGE/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
if [ -x /usr/bin/umbra ]; then
  /usr/bin/umbra normal || true
fi
if [ "$1" = "remove" ] || [ "$1" = "purge" ] || [ "$1" = "deconfigure" ]; then
  systemctl disable --now umbra-boot.service >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 0755 "$STAGE/DEBIAN/prerm"

cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
systemctl daemon-reload >/dev/null 2>&1 || true
command -v mandb >/dev/null 2>&1 && mandb -q >/dev/null 2>&1 || true
exit 0
EOF
chmod 0755 "$STAGE/DEBIAN/postinst"

# Normalize permissions: dpkg-deb requires DEBIAN/ and dirs to be 0755, but a
# restrictive root umask (e.g. 027 on hardened Kali) yields 0750. Set them.
find "$STAGE" -type d -exec chmod 0755 {} +
find "$STAGE" -type f -exec chmod 0644 {} +
chmod 0755 "$STAGE/usr/bin/umbra" "$STAGE/DEBIAN/prerm" "$STAGE/DEBIAN/postinst" \
           "$STAGE/etc/NetworkManager/dispatcher.d/50-umbra"

mkdir -p "$SRC/dist"
DEB="$SRC/dist/umbra_${VERSION}_${ARCH}.deb"
dpkg-deb --root-owner-group --build "$STAGE" "$DEB"
echo "built: $DEB"
