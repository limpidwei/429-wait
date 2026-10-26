# 429-wait

Install once, forget forever. When your CLI agent hits a rate limit, 429-wait automatically waits for quota to restore and re-launches your session.

![429-wait in action](assets/demo-screenshot.png)

```
claude --flag1 --flag2      # you type this as usual
  |                         
  v                         
429-wait shim (transparent) 
  |                         
  +-> runs real claude      
  +-> agent hits limit, exits
  +-> detects rate limit (exit code + stderr)
  +-> probes API every 5 min
  +-> quota restored!
  +-> re-launches: claude --continue
```

No behavior change. No daemon to start. The shim lives in your PATH and wraps the real binary transparently.

## Supported Agents

| Agent | Recovery | Notes |
|---|---|---|
| **Claude Code** | `claude --continue` | Resumes most recent session |
| **Codex CLI** | Replay original command | OpenAI rate limits |
| **Aider** | Replay original command | Non-interactive mode only (`aider --message`) |

## Quick Start

### Windows

```powershell
git clone https://github.com/limpidwei/429-wait.git
pwsh 429-wait\install.ps1
```

### macOS / Linux

```bash
git clone https://github.com/limpidwei/429-wait.git
bash 429-wait/install.sh
```

The installer:
1. Copies the shim + adapters to `~/.local/bin`
2. Auto-detects which agents you have installed (claude, codex, aider)
3. Generates a transparent wrapper for each one
4. Writes a manifest for clean uninstall

After install, just use your agents as usual. Rate limits are handled automatically.

## How It Works

1. **Shim intercepts**: Your `claude` command is actually a thin wrapper that calls `429-wait-shim.py`
2. **Pass-through**: The shim finds the real binary (skipping itself in PATH), runs it with your args. Stdout passes through untouched (TUI-safe). Stderr is captured while still displayed in real time.
3. **Detection**: When the agent exits, the shim checks exit code + stderr against adapter-defined patterns (e.g. "hit usage limit", "429", "rate limit")
4. **Probe loop**: On rate-limit detection, probes the actual API endpoint (Anthropic or OpenAI) every 5 minutes with a minimal request (`max_tokens=64`)
5. **Recovery**: Once the API responds 200, re-launches the agent with the appropriate recovery strategy

## Probe Cost

Each probe sends a minimal request: `{"messages":[{"role":"user","content":"hi"}], "max_tokens":64}`. At default 5-minute intervals over a typical 4-hour wait:

- **48 probes** x ~100 input tokens + ~64 output tokens
- **Anthropic**: ~$0.02 total (Claude Sonnet pricing)
- **OpenAI**: ~$0.01 total

## Adapters

Each agent has a TOML config in `adapters/`. Example (`claude-code.toml`):

```toml
[agent]
name = "claude-code"
command = "claude"

[detection]
exit_codes = [1]
require_stderr_match = true
stderr_patterns = ["hit usage limit", "rate limit", "429"]

[probe]
type = "http"
endpoint_path = "/v1/messages"
# credentials from env vars or ~/.claude/settings.json

[recovery]
strategy = "continue"              # or "replay"
command_template = "{command} --continue"
```

To add a new agent: create `adapters/your-agent.toml` following the same format, then re-run the installer.

## Standalone Daemon (v2)

The original probe-only daemon is still available for manual use:

```bash
python 429-wait.py --interval 300 --tag mytask \
    --on-recover "claude --continue"
```

Useful when you want to start waiting manually without the shim. Reads credentials from `~/.claude/settings.json` or env vars.

### Why v2 over v1

| v1 problem | What actually happens | v2 fix |
|---|---|---|
| `claude -p ping` as probe | Claude Code retries 429 internally forever, probe never returns | Direct HTTP to `/v1/messages`, 25s hard timeout |
| Tiny `max_tokens` | Relays that meter by declared max_tokens: `max_tokens=1` passes even when exhausted | Default `max_tokens=64` (calibrated) |
| Log tailing | TUI-only limit message, never written to log file | Active polling, no log source needed |

## Uninstall

```powershell
# Windows
pwsh uninstall.ps1

# macOS / Linux
bash uninstall.sh
```

Removes shims, scripts, and adapters. Logs in `~/.429-wait/` are preserved.

## Requirements

- Python 3.8+ (uses only stdlib, zero pip dependencies)
- API credentials configured for your agent (the shim reads them the same way the agent does)

## Testing

```bash
python tests/shim-e2e.py       # Full shim cycle: mock agent + mock probe, zero real API calls
python tests/real-probe-test.py # Real-network smoke test with fake API key ($0 cost)
python tests/demo-scenario.py   # Realistic demo for screenshots
python tests/py-e2e.py          # Standalone daemon test
pwsh tests/e2e-test.ps1         # Legacy v1 PowerShell test
```

## Project Structure

```
adapters/
  claude-code.toml    # Claude Code adapter
  codex.toml          # Codex CLI adapter
  aider.toml          # Aider adapter
bin/
  429-wait-shim.py    # Core shim (transparent wrapper)
  429-wait.py         # Standalone probe daemon (v2)
  429-wait.ps1        # Legacy v1 PowerShell daemon
  429-wait-watch.ps1  # Legacy v1 log watcher
  429-wait.sh         # Legacy v1 bash daemon
tests/
  shim-e2e.py         # Shim end-to-end test
  real-probe-test.py   # Real-network smoke test
  demo-scenario.py     # Promotional demo
  py-e2e.py           # Standalone daemon test
install.ps1           # Windows installer
install.sh            # macOS/Linux installer
uninstall.ps1         # Windows uninstaller
uninstall.sh          # macOS/Linux uninstaller
```

## License

MIT
