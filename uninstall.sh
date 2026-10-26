#!/usr/bin/env bash
set -euo pipefail

# 429-wait uninstaller for macOS / Linux
# Reads the install manifest and removes everything.

STATE_DIR="$HOME/.429-wait"
MANIFEST="$STATE_DIR/manifest.json"

if [ ! -f "$MANIFEST" ]; then
    echo "429-wait: manifest not found. Nothing to uninstall."
    echo "  (expected at $MANIFEST)"
    exit 0
fi

DEST=$(python3 -c "import json; print(json.load(open('$MANIFEST'))['dest'])")
ADAPTER_DEST=$(python3 -c "import json; print(json.load(open('$MANIFEST'))['adapter_dest'])")

echo "Uninstalling 429-wait ..."

# remove shims
for cmd in $(python3 -c "import json; [print(s) for s in json.load(open('$MANIFEST')).get('shims',[])]"); do
    p="$DEST/$cmd"
    if [ -f "$p" ]; then
        rm -f "$p"
        echo "  removed shim: $p"
    fi
done

# remove core files
for f in $(python3 -c "import json; [print(s) for s in json.load(open('$MANIFEST')).get('files',[])]"); do
    p="$DEST/$f"
    if [ -f "$p" ]; then
        rm -f "$p"
        echo "  removed: $p"
    fi
done

# remove legacy files
for f in 429-wait.sh 429-wait.ps1 429-wait-watch.ps1; do
    p="$DEST/$f"
    [ -f "$p" ] && rm -f "$p" && echo "  removed legacy: $p"
done

# remove adapters
if [ -d "$ADAPTER_DEST" ]; then
    rm -rf "$ADAPTER_DEST"
    echo "  removed adapters: $ADAPTER_DEST"
fi

# remove manifest
rm -f "$MANIFEST"
echo "  removed manifest"

echo ""
echo "Done. 429-wait has been uninstalled."
echo "Note: state/logs in $STATE_DIR were preserved. Delete manually if not needed."
