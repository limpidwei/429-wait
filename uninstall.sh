#!/usr/bin/env bash
set -euo pipefail

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

if [ -f "$DEST/429-wait-settings.py" ]; then
    python3 "$DEST/429-wait-settings.py" uninstall --hook-script "$DEST/429-wait-hook.py"
fi

for cmd in $(python3 -c "import json; [print(s) for s in json.load(open('$MANIFEST')).get('shims',[])]"); do
    p="$DEST/$cmd"
    if [ -f "$p" ] && grep -Eq '429-wait-(shim|terminal)\.py' "$p"; then
        rm -f "$p"
        echo "  removed shim: $p"
    fi
done

for f in $(python3 -c "import json; [print(s) for s in json.load(open('$MANIFEST')).get('files',[])]"); do
    p="$DEST/$f"
    if [ -f "$p" ]; then
        rm -f "$p"
        echo "  removed: $p"
    fi
done

for f in 429-wait.sh 429-wait.ps1 429-wait-watch.ps1; do
    p="$DEST/$f"
    [ -f "$p" ] && rm -f "$p" && echo "  removed legacy: $p"
done

if [ -d "$ADAPTER_DEST" ]; then
    rm -rf "$ADAPTER_DEST"
    echo "  removed adapters: $ADAPTER_DEST"
fi

rm -f "$MANIFEST"
echo "  removed manifest"

echo ""
echo "Done. 429-wait has been uninstalled."
echo "Note: state/logs in $STATE_DIR were preserved. Delete manually if not needed."
