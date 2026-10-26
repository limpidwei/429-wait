#!/usr/bin/env bash
set -euo pipefail

# 429-wait installer for macOS / Linux
# Copies shim + adapters, generates per-agent wrapper scripts.

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.local/bin"
ADAPTER_DEST="$HOME/.local/share/429-wait/adapters"
MANIFEST="$HOME/.429-wait/manifest.json"

mkdir -p "$DEST" "$ADAPTER_DEST" "$HOME/.429-wait"

echo "Installing 429-wait to $DEST ..."

# copy core files
cp "$SRC/bin/429-wait-shim.py" "$DEST/"
cp "$SRC/bin/429-wait.py"      "$DEST/"  # standalone daemon (v2)
chmod +x "$DEST/429-wait-shim.py" "$DEST/429-wait.py"

# copy adapters
for f in "$SRC"/adapters/*.toml; do
    [ -f "$f" ] && cp "$f" "$ADAPTER_DEST/"
done

# copy legacy scripts if present
for f in 429-wait.sh 429-wait.ps1 429-wait-watch.ps1; do
    [ -f "$SRC/bin/$f" ] && cp "$SRC/bin/$f" "$DEST/"
done
chmod +x "$DEST/429-wait.sh" 2>/dev/null || true

# detect agents and generate shims
SHIMS_CREATED=()

generate_shim() {
    local agent_name="$1"  # e.g. claude-code
    local command="$2"     # e.g. claude
    local shim_path="$DEST/$command"

    # check if real binary exists (skip shim dir)
    local real_bin
    real_bin=$(PATH=$(echo "$PATH" | tr ':' '\n' | grep -v "^${DEST}$" | tr '\n' ':') command -v "$command" 2>/dev/null || true)
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

generate_shim "claude-code" "claude"
generate_shim "codex"       "codex"
generate_shim "aider"       "aider"

# write manifest
cat > "$MANIFEST" <<EOF
{
  "installed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "dest": "$DEST",
  "adapter_dest": "$ADAPTER_DEST",
  "shims": [$(printf '"%s",' "${SHIMS_CREATED[@]}" | sed 's/,$//')]  ,
  "files": [
    "429-wait-shim.py",
    "429-wait.py"
  ]
}
EOF

# check PATH
if ! echo "$PATH" | tr ':' '\n' | grep -qx "$DEST"; then
    echo ""
    echo "WARNING: $DEST is not in your PATH."
    echo "Add this to your ~/.bashrc or ~/.zshrc:"
    echo "  export PATH=\"$DEST:\$PATH\""
    echo ""
fi

echo ""
echo "Done! Installed:"
[ ${#SHIMS_CREATED[@]} -gt 0 ] && echo "  shims: ${SHIMS_CREATED[*]}"
echo "  adapters: $ADAPTER_DEST/"
echo "  standalone daemon: 429-wait.py (python3 $DEST/429-wait.py --help)"
echo ""
echo "Uninstall: bash $(dirname "$0")/uninstall.sh"
