#!/usr/bin/env bash
set -euo pipefail

# Claude Code uses StopFailure hooks; other agents keep command shims.
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.local/bin"
ADAPTER_DEST="$HOME/.local/share/429-wait/adapters"
MANIFEST="$HOME/.429-wait/manifest.json"

mkdir -p "$DEST" "$ADAPTER_DEST" "$HOME/.429-wait"

echo "Installing 429-wait to $DEST ..."

cp "$SRC/bin/429-wait-shim.py" "$DEST/"
cp "$SRC/bin/429-wait.py" "$DEST/"
cp "$SRC/bin/429-wait-hook.py" "$DEST/"
cp "$SRC/bin/429-wait-settings.py" "$DEST/"
cp "$SRC/bin/429-wait-terminal.py" "$DEST/"
chmod +x "$DEST/429-wait-shim.py" "$DEST/429-wait.py" "$DEST/429-wait-hook.py" "$DEST/429-wait-settings.py" "$DEST/429-wait-terminal.py"

for f in "$SRC"/adapters/*.toml; do
    [ -f "$f" ] && cp "$f" "$ADAPTER_DEST/"
done

for f in 429-wait.sh 429-wait.ps1 429-wait-watch.ps1; do
    [ -f "$SRC/bin/$f" ] && cp "$f" "$DEST/"
done
chmod +x "$DEST/429-wait.sh" 2>/dev/null || true

SHIMS_CREATED=()
HOOK_INSTALLED=false

find_real() {
    PATH=$(echo "$PATH" | tr ':' '\n' | grep -v "^${DEST}$" | tr '\n' ':') command -v "$1" 2>/dev/null || true
}

install_claude_hook() {
    local real_bin
    real_bin=$(find_real claude)
    if [ -z "$real_bin" ]; then
        echo "  skip claude (not found in PATH)"
        return
    fi
    if [ -f "$DEST/claude" ] && grep -Eq '429-wait-(shim|terminal)\.py' "$DEST/claude"; then
        rm -f "$DEST/claude"
        echo "  replaced previous Claude wrapper: $DEST/claude"
    fi
    python3 "$DEST/429-wait-settings.py" install --hook-script "$DEST/429-wait-hook.py"
    cat > "$DEST/claude" <<SHIM
#!/bin/sh
exec python3 "$DEST/429-wait-terminal.py" --shim-dir "$DEST" -- "\$@"
SHIM
    chmod +x "$DEST/claude"
    SHIMS_CREATED+=("claude")
    HOOK_INSTALLED=true
    echo "  supervisor + hook: Claude Code -> same-window, same-session recovery"
}

generate_shim() {
    local agent_name="$1"
    local command="$2"
    local shim_path="$DEST/$command"
    local real_bin
    real_bin=$(find_real "$command")
    if [ -z "$real_bin" ]; then
        echo "  skip $command (not found in PATH)"
        return
    fi

    cat > "$shim_path" <<SHIM
#!/bin/sh
exec python3 "$DEST/429-wait-shim.py" --adapter "$agent_name" --shim-dir "$DEST" -- "\$@"
SHIM
    chmod +x "$shim_path"
    SHIMS_CREATED+=("$command")
    echo "  shim: $shim_path -> $real_bin"
}

install_claude_hook
generate_shim "codex" "codex"
generate_shim "aider" "aider"

SHIMS_JSON=$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1:]))' "${SHIMS_CREATED[@]}")
cat > "$MANIFEST" <<EOF
{
  "installed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "dest": "$DEST",
  "adapter_dest": "$ADAPTER_DEST",
  "shims": $SHIMS_JSON,
  "hook_installed": $HOOK_INSTALLED,
  "files": [
    "429-wait-shim.py",
    "429-wait.py",
    "429-wait-hook.py",
    "429-wait-settings.py",
    "429-wait-terminal.py"
  ]
}
EOF

if ! echo "$PATH" | tr ':' '\n' | grep -qx "$DEST"; then
    echo ""
    echo "WARNING: $DEST is not in your PATH."
    echo "Add this to your ~/.bashrc or ~/.zshrc:"
    echo "  export PATH=\"$DEST:\$PATH\""
    echo ""
fi

echo ""
echo "Done! Installed:"
echo "  Claude Code StopFailure hook: $HOOK_INSTALLED"
echo "  supervised commands: ${SHIMS_CREATED[*]:-}"
echo "  standalone daemon: 429-wait.py (python3 $DEST/429-wait.py --help)"
echo ""
echo "Uninstall: bash $(dirname "$0")/uninstall.sh"
