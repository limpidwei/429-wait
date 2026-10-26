# 429-wait

**English** | [中文](#中文)

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

---

<a id="中文"></a>

# 429-wait

[English](#429-wait) | **中文**

装一次，永久生效。CLI Agent 撞上额度限制时，429-wait 自动守候、自动探测、自动恢复运行。

![429-wait 效果演示](assets/demo-screenshot.png)

```
claude --flag1 --flag2      # 照常使用
  |                         
  v                         
429-wait shim（透明垫片）   
  |                         
  +-> 运行真正的 claude      
  +-> agent 撞限，退出
  +-> 检测到限额（退出码 + stderr）
  +-> 每 5 分钟探测 API
  +-> 额度恢复！
  +-> 自动重启：claude --continue
```

无需改变任何习惯。不用手动启动守护进程。垫片装在 PATH 里，透明包裹真实二进制。

## 支持的 Agent

| Agent | 恢复方式 | 备注 |
|---|---|---|
| **Claude Code** | `claude --continue` | 恢复最近一次会话 |
| **Codex CLI** | 重放原始命令 | OpenAI 限额 |
| **Aider** | 重放原始命令 | 仅支持非交互模式（`aider --message`） |

## 快速开始

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

安装器会：
1. 将垫片和适配器复制到 `~/.local/bin`
2. 自动检测已安装的 agent（claude、codex、aider）
3. 为每个 agent 生成透明包裹脚本
4. 写入清单文件，方便卸载

安装后照常使用你的 agent，限额恢复全自动处理。

## 工作原理

1. **垫片拦截**：你的 `claude` 命令实际调用 `429-wait-shim.py`
2. **透传**：垫片在 PATH 中找到真正的二进制（跳过自身目录），用你的参数运行。Stdout 原样透传（TUI 安全），stderr 实时显示的同时被捕获
3. **检测**：agent 退出时，垫片检查退出码 + stderr 是否匹配适配器定义的模式（如 "hit usage limit"、"429"）
4. **探测循环**：检测到限额后，每 5 分钟向真实 API 端点（Anthropic 或 OpenAI）发送最小请求（`max_tokens=64`）
5. **恢复**：API 返回 200 后，用对应策略重新启动 agent

## 探测成本

每次探测发送最小请求：`{"messages":[{"role":"user","content":"hi"}], "max_tokens":64}`。按默认 5 分钟间隔、典型 4 小时等待：

- **48 次探测** x 约 100 输入 token + 约 64 输出 token
- **Anthropic**：总计约 $0.02（Claude Sonnet 价格）
- **OpenAI**：总计约 $0.01

## 适配器

每个 agent 在 `adapters/` 下有一份 TOML 配置。示例（`claude-code.toml`）：

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
# 凭证来自环境变量或 ~/.claude/settings.json

[recovery]
strategy = "continue"              # 或 "replay"
command_template = "{command} --continue"
```

添加新 agent：按相同格式创建 `adapters/your-agent.toml`，然后重新运行安装器。

## 独立守护进程（v2）

原始的纯探测守护进程仍可手动使用：

```bash
python 429-wait.py --interval 300 --tag mytask \
    --on-recover "claude --continue"
```

适用于不想用垫片、想手动启动等待的场景。凭证从 `~/.claude/settings.json` 或环境变量读取。

### v2 相比 v1 的改进

| v1 问题 | 实际表现 | v2 修复 |
|---|---|---|
| 用 `claude -p ping` 做探测 | Claude Code 内部无限重试 429，探测永远不返回 | 直接 HTTP 请求 `/v1/messages`，25 秒硬超时 |
| `max_tokens` 太小 | 按声明值计量的中继：`max_tokens=1` 即使额度耗尽也能通过 | 默认 `max_tokens=64`（已校准） |
| 尾随日志 | 限额提示只在 TUI 显示，不写入日志文件 | 主动轮询，不依赖日志源 |

## 卸载

```powershell
# Windows
pwsh uninstall.ps1

# macOS / Linux
bash uninstall.sh
```

移除垫片、脚本和适配器。`~/.429-wait/` 中的日志会保留。

## 环境要求

- Python 3.8+（仅使用标准库，零 pip 依赖）
- 已配置 agent 对应的 API 凭证（垫片读取方式与 agent 相同）

## 测试

```bash
python tests/shim-e2e.py       # 完整垫片循环：mock agent + mock 探测服务器，零真实 API 调用
python tests/real-probe-test.py # 真实网络冒烟测试：假 API key，$0 成本
python tests/demo-scenario.py   # 逼真演示场景，用于截图
python tests/py-e2e.py          # 独立守护进程测试
pwsh tests/e2e-test.ps1         # 旧版 v1 PowerShell 测试
```

## 项目结构

```
adapters/
  claude-code.toml    # Claude Code 适配器
  codex.toml          # Codex CLI 适配器
  aider.toml          # Aider 适配器
bin/
  429-wait-shim.py    # 核心垫片（透明包裹器）
  429-wait.py         # 独立探测守护进程（v2）
  429-wait.ps1        # 旧版 v1 PowerShell 守护
  429-wait-watch.ps1  # 旧版 v1 日志监视器
  429-wait.sh         # 旧版 v1 bash 守护
tests/
  shim-e2e.py         # 垫片端到端测试
  real-probe-test.py   # 真实网络冒烟测试
  demo-scenario.py     # 宣发演示
  py-e2e.py           # 独立守护进程测试
install.ps1           # Windows 安装器
install.sh            # macOS/Linux 安装器
uninstall.ps1         # Windows 卸载器
uninstall.sh          # macOS/Linux 卸载器
```

## 许可证

MIT
