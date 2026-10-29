# 429-wait

**English** | [中文](#中文)

Wait out an LLM usage limit, then continue the same conversation in the same terminal.

For supervised Claude Code sessions, a `StopFailure` hook notifies the terminal supervisor after the final rate-limit failure. The original TUI stays visible while a per-session watchdog probes the API. Once quota recovers, the supervisor stops the idle Claude process and resumes the **same session_id in the same window**. Background fork is only a fallback for unsupervised or uncertain states.

## The problem

Interactive Claude Code does not necessarily exit on a 429. It retries internally, ends the current turn, and waits for input. The quota can reset hours later without any new request being made. Tools that wait only for process exit or scrape stderr miss this case. A background-only recovery also hides subsequent output from the original conversation.

## How it works

```text
claude (started through the terminal supervisor)
  → final 429: StopFailure writes a per-window event
  → original TUI stays open; a probe-only watchdog starts
  → manual input or exit cancels automatic recovery
  → HTTP 200 + stable idle state: stop the old Claude process
  → claude --resume SAME_SESSION_ID 继续 (interactive, same terminal)
  → subsequent output appears in the original conversation
```

- **Same window, same session.** No `--continue` and no default `--fork-session`.
- **User control first.** A new typed prompt cancels recovery; manual exit never triggers a restart.
- **Parallel windows are independent.** Supervisor tokens and per-session state prevent cross-session recovery.
- **Direct HTTP probes.** No terminal scraping and no `claude -p ping`. Probes use a hard timeout and `max_tokens=64`.
- **Three-state classification.** HTTP 200 means recovered; quota/auth responses keep waiting; network errors are not mistaken for recovery.
- **No privilege expansion.** Recovery preserves configuration flags and adds no bypass-permission flags.

Codex and Aider retain the older transparent-shim path. That path only works when the agent exits with a matching stderr error; it is not the Claude Code path.

## Supported agents

| Agent | Trigger | Recovery |
|---|---|---|
| Claude Code | `StopFailure` + terminal supervisor | Same window, same session_id |
| Codex CLI | Legacy exit-code + stderr shim | Replay the original command |
| Aider | Legacy exit-code + stderr shim | Replay non-interactive command |

## Quick start

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

The installer copies the supervisor, hook, watchdog and settings helper, adds one owned `StopFailure` hook while preserving existing settings, and generates a Claude wrapper connected to the real binary. Existing wrappers are replaced only when their contents identify them as 429-wait files.

Start Claude through the normal `claude` command after installation. Newly started or reopened windows are supervised; an already running unsupervised TUI cannot be retroactively attached. State and logs live under `~/.429-wait/`.

## Manual watchdog and background fallback

The standalone probe remains available for custom recovery commands:

```bash
python bin/429-wait.py --interval 300 --tag mytask \
    --on-recover "your recovery command"
```

The structured background fallback for an unsupervised Claude session is:

```bash
python bin/429-wait.py \
    --session-id SESSION_ID --cwd PROJECT_DIR \
    --recover-agent claude-code
```

It uses `--resume OLD_ID --fork-session -p 继续` and records the new session_id. This is not the default supervised-TUI path.

## Uninstall

```powershell
# Windows
pwsh uninstall.ps1

# macOS / Linux
bash uninstall.sh
```

Uninstall removes only the owned hook, scripts, adapters and generated wrappers. Other settings and hooks are preserved. Logs under `~/.429-wait/` are retained.

## Requirements

- Python 3.8+; standard library only.
- Claude Code with `StopFailure` support for the Claude path.
- API credentials in the agent environment or Claude settings.

## Testing

Default end-to-end tests use local mocks and do not consume API quota.

```bash
python tests/terminal-e2e.py   # same-window state machine, manual takeover, two windows, repeat 429
python tests/hook-e2e.py       # background fallback, dedupe, two sessions, handoff
python tests/settings-e2e.py   # settings install/uninstall and preservation
python tests/py-e2e.py         # probe and legacy on-recover cycle
python tests/shim-e2e.py       # legacy shim cycle for other agents
python tests/real-probe-test.py
python tests/demo-scenario.py
pwsh tests/install-e2e.ps1     # isolated Windows install/upgrade/uninstall
```

The release gate is a real interactive Claude TUI in a spare Windows Terminal, using an isolated config and local fake API. Recovery must appear in the original session transcript; a `-p`-only test is not sufficient.

## Evolution

| Version | Approach | Limitation addressed |
|---|---|---|
| v1 | Log tailing + `claude -p ping` | Missing TUI logs and hanging CLI probes |
| v2 | Direct HTTP watchdog | Manual startup and session discovery |
| v3 | Exit/stderr shim | Misses interactive sessions that stay open |
| v4 | StopFailure + background fork | Automatic recovery, but output is hidden from the original TUI |
| v5 | Terminal supervisor + same-session resume | Restores output and control in the original conversation |

## Project structure

```text
adapters/                 # Legacy shim adapter configs
bin/
  429-wait-terminal.py    # Same-window supervisor and session state machine
  429-wait-hook.py        # StopFailure event notification / fallback launcher
  429-wait-settings.py    # Idempotent settings install/remove helper
  429-wait.py             # Probe watchdog and background fallback recovery
  429-wait-shim.py        # Legacy shim for other agents
  429-wait.ps1/.sh        # Legacy v1 scripts
  429-wait-watch.ps1      # Legacy log watcher
tests/                    # Local-mock end-to-end tests
install.ps1 / install.sh
uninstall.ps1 / uninstall.sh
```

## License

MIT

---

<a id="中文"></a>

# 429-wait

[English](#429-wait) | **中文**

等待 LLM 额度恢复，然后在**原终端、原对话**中继续。

对于由监督器启动的 Claude Code，最终限流失败时，`StopFailure` 只负责通知终端监督器。原 TUI 保持可见，每会话探针在后台等待额度；恢复后，监督器停止已空闲的旧进程，并在**同一窗口、使用同一 session_id**继续。后台 fork 仅用于非监督或状态无法确认的兜底场景。

## 要解决的问题

交互式 Claude Code 遇到 429 后不一定退出，而是结束本轮并等待输入。只等待“进程退出＋stderr”的工具会漏掉这个场景；只恢复成后台新会话又会让用户失去原对话中的输出和掌控感。

## 工作原理

```text
claude（由终端监督器启动）
  → 最终429：StopFailure 写入当前窗口专属事件
  → 原 TUI 保留，probe-only 守候器启动
  → 用户手动继续或退出会取消自动恢复
  → 探测200且状态稳定：停止旧 Claude 进程
  → claude --resume 原session_id 继续（交互式、原终端）
  → 后续输出直接出现在原对话
```

- **原窗口、原会话**：不使用 `--continue`，默认不创建 fork。
- **用户操作优先**：新的手动输入取消恢复，手动退出不会触发重启。
- **多窗口独立**：监督器 token 和每会话状态避免接错对话。
- **直接 HTTP 探测**：不刮终端，也不使用会在内部重试的 CLI 探针。
- **不提升权限**：保留原配置参数，不添加绕过权限的参数。

Codex 和 Aider 保留旧的透明 shim 路径，不再用于 Claude Code。

## 支持的 Agent

| Agent | 触发 | 恢复 |
|---|---|---|
| Claude Code | `StopFailure`＋终端监督器 | 原窗口、原 session_id |
| Codex CLI | 旧版退出码＋stderr shim | 重放原命令 |
| Aider | 旧版退出码＋stderr shim | 重放非交互命令 |

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

安装后仍照常使用 `claude`。新启动或重开的窗口由监督器接管；已经运行且未经监督器启动的 TUI 无法 retroactively 接管。状态和日志位于 `~/.429-wait/`。

## 手动守候与后台兜底

```bash
python bin/429-wait.py --interval 300 --tag mytask \
    --on-recover "你的恢复命令"
```

非监督会话的结构化后台兜底：

```bash
python bin/429-wait.py \
    --session-id SESSION_ID --cwd PROJECT_DIR \
    --recover-agent claude-code
```

它会 fork 新会话并记录新 ID，但这不是默认的同窗口路径。

## 卸载

```powershell
pwsh uninstall.ps1
# 或 macOS / Linux
bash uninstall.sh
```

只移除自己的 Hook、脚本、适配器和生成的 wrapper，保留其他配置与日志。

## 环境要求

- Python 3.8+，仅标准库。
- Claude 路径需要支持 `StopFailure` 的 Claude Code。
- Agent 环境或 Claude settings 中已配置 API 凭证。

## 测试

```bash
python tests/terminal-e2e.py
python tests/hook-e2e.py
python tests/settings-e2e.py
python tests/py-e2e.py
python tests/shim-e2e.py
python tests/real-probe-test.py
python tests/demo-scenario.py
pwsh tests/install-e2e.ps1
```

默认测试全部使用本地 mock。切换默认安装前，还必须在备用 Windows Terminal 中用真实交互式 Claude＋隔离假 API 验证：恢复文本出现在原 session_id 的记录里，不能只跑 `-p`。

## 版本演进

| 版本 | 方案 | 解决的问题 |
|---|---|---|
| v1 | 日志尾随＋CLI 探针 | TUI 日志缺失、CLI 探针卡死 |
| v2 | 直连 HTTP 守候 | 手动启动和会话发现问题 |
| v3 | 退出码＋stderr shim | 漏掉429后仍打开的交互会话 |
| v4 | Hook＋后台 fork | 能恢复，但原窗口看不到后续输出 |
| v5 | 终端监督器＋同会话重启 | 恢复原对话中的输出和掌控感 |

## 许可证

MIT
