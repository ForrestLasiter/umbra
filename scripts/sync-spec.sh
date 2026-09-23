#!/usr/bin/env bash
# Regenerate the core spec and copy it into every platform adapter's resources,
# so the Linux reference, the Android app, and the iOS app can never drift.
#
#   scripts/sync-spec.sh
#
# Run it after changing profiles, capabilities, or the platform matrix.
set -euo pipefail
cd "$(dirname "$0")/.."

# 1) Regenerate spec/umbra-core.json (+ schema) from the Python core.
if command -v umbra >/dev/null 2>&1; then
  umbra export-spec >/dev/null
else
  python -m umbra.cli export-spec >/dev/null
fi

# 2) Fan out to the mobile adapters.
cp spec/umbra-core.json android/app/src/main/assets/umbra-core.json
mkdir -p ios/Umbra/Resources
cp spec/umbra-core.json ios/Umbra/Resources/umbra-core.json

echo "synced spec/umbra-core.json -> android assets + ios resources"
