# 429-wait

> 额度用尽不用熬夜等。一个后台 shell，帮你的 AI agent 蹲到额度恢复，自动接着干活。
> Hit an LLM usage limit at 1 AM? A tiny background shell polls until quota resets, then resumes the task — no computer-use agent, no token burn.
>
> 前身：[cc-resume](https://github.com/limpidwei/cc-resume)（UI Automation 敲回车方案，已归档）。429-wait 是它的纯 shell 重写。

## 解决什么问题

夜里用 Claude Code / 其他 agent CLI 跑长任务，撞上 `hit usage limit`（403/429），任务就断在那儿。额度几小时后自动恢复，但你已经睡了。

429-wait 用一个**后台守护 shell**解决这个问题：

1. **触发**：agent 日志里一旦出现 usage limit 错误，watcher 自动拉起 429-wait 守护进程（也可以手动拉起）
2. **守候**：429-wait 每 30 分钟（可配）跑一次极轻量探测命令，确认额度是否恢复
3. **复活**：探测成功 → 自动执行你指定的 resume 命令（例如 `claude --continue -p continue` 接着跑任务）→ 429-wait 自己退出

全程不开浏览器、不用 computer use、不烧额外 token——每次探测只有一个最小请求。

## 安装

```powershell
git clone https://github.com/limpidwei/429-wait.git
pwsh 429-wait\install.ps1   # 装到 ~/.local/bin（已在 PATH），生成 .cmd 全局命令
```

Linux / macOS / Termux 直接用 `bin/429-wait.sh`，或 `bin/429-wait.py`（只需 python3）。

## v2：Python 版（推荐）

`bin/429-wait.py` 是同一件事的重写，因为 v1 的"探测一条命令"模型实测有三个坑：

| v1 的坑 | 实际发生了什么 | v2 怎么绕开 |
|---|---|---|
| 用 `claude -p ping` 当探针 | Claude Code 撞 429 会**内部无限重试**，永不返回 → 守护进程卡死在第一次探测 | 直连 HTTP 打 `/v1/messages`，25 秒硬超时 |
| 探针用极小的 `max_tokens` | 按 `max_tokens` 计量的中转站：额度耗尽时 `max_tokens=1` 仍返回 200，假恢复 | 默认 `--probe-max-tokens 64`（实测校准值） |
| 靠 tail 日志发现限额 | 限额提示只出现在 TUI，**不写日志** → watcher 永远读不到输入 | 主动轮询，不需要任何日志源 |

端点/密钥/模型默认读 `~/.claude/settings.json` 的 `env`（`ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL`）。

```bash
python bin/429-wait.py --interval 300 --tag mytask \
    --on-recover "claude --resume <session-id> -p continue"
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--interval` | 300 | 两次探测间隔（秒） |
| `--max-attempts` | 120 | 最大探测次数，超了退出码 2 |
| `--on-recover` | 空 | 恢复后执行的续跑命令 |
| `--probe-max-tokens` | 64 | 探针 max_tokens；小于 64 可能被计费式中转站误报 200 |
| `--tag` / `--state-dir` | `default` / `~/.429-wait` | 实例标签（同标签单实例）、状态目录 |
| `--settings` | `~/.claude/settings.json` | 凭据来源，可用 `--base-url/--api-key/--model` 覆盖 |

网络抖动（非 429/401/403 的错误）不算恢复，会继续等——只在探测真的拿到 200 时才写 `nanny-<tag>.ok` 并执行 `--on-recover`。

## 用法

### 手动拉起（知道已经撞墙了）

```powershell
429-wait.cmd -ProbeCommand "claude -p ping --max-turns 1" `
             -ResumeCommand "claude --continue -p 'continue the task'" `
             -IntervalSeconds 1800
```

```bash
429-wait.sh --probe "claude -p ping" \
            --resume "claude --continue -p continue" \
            --interval 1800
```

### 自动触发（盯着 agent 日志，撞墙自动拉起）

```powershell
429-wait-watch.cmd -LogFile "C:\path\to\agent-session.log" `
                   -ProbeCommand "claude -p ping --max-turns 1" `
                   -ResumeCommand "claude --continue -p 'continue'"
```

### 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `-ProbeCommand` / `--probe` | （必填） | 探测命令，越轻越好 |
| `-ResumeCommand` / `--resume` | 空 | 额度恢复后要执行的续跑命令 |
| `-IntervalSeconds` / `--interval` | 1800 | 重试间隔（秒） |
| `-MaxAttempts` / `--max-attempts` | 48 | 最大重试次数（默认守 24 小时后放弃） |
| `-LimitPattern` / `--pattern` | `usage limit\|hit.*limit\|rate.?limit\|quota\|429\|403\|overloaded\|exceeded` | 判定"仍被限流"的正则 |
| `-Tag` / `--tag` | `default` | 实例标签，同标签单实例运行 |

状态与日志在 `~/.429-wait/`：`nanny-<tag>.log`（探测记录）、`nanny-<tag>.ok`（恢复哨兵文件）。

## 设计原则

- **不用 GUI 自动化**：探测和续跑都是 CLI 调用，比 computer-use 方案便宜几个数量级
- **单实例**：同一 tag 只跑一个守护进程，重复触发会自己退出
- **自我了断**：额度恢复（或超过最大重试）即退出，不留残余进程

## 测试

仓库自带 mock LLM 和端到端测试（不碰真实 API）：

```powershell
pwsh tests\e2e-test.ps1      # 守护进程：常驻→定时重试→恢复自动退出
pwsh tests\watch-test.ps1    # watcher：日志出现 limit → 自动拉起守护进程
python tests\py-e2e.py       # v2：本地 mock 先 429 两次再 200，验证恢复+续跑
```

## English summary

A zero-GUI usage-limit watchdog for LLM agent CLIs. When your agent hits `usage limit` / 403 / 429, a background daemon probes every N minutes with a minimal request; once quota recovers it runs your resume command (e.g. re-invoking the agent with "continue") and exits. PowerShell + bash, single-instance, self-terminating. Ships with a mock LLM and e2e tests that never touch a real API.

## License

MIT
