# quota-nanny

> 额度用尽不用熬夜等。一个后台 shell，帮你的 AI agent 蹲到额度恢复，自动接着干活。
> Hit an LLM usage limit at 1 AM? A tiny background shell polls until quota resets, then resumes the task — no computer-use agent, no token burn.

## 解决什么问题

夜里用 Claude Code / 其他 agent CLI 跑长任务，撞上 `hit usage limit`（403/429），任务就断在那儿。额度几小时后自动恢复，但你已经睡了。

quota-nanny 用一个**后台守护 shell**解决这个问题：

1. **触发**：agent 日志里一旦出现 usage limit 错误，watcher 自动拉起 nanny 守护进程（也可以手动拉起）
2. **守候**：nanny 每 30 分钟（可配）跑一次极轻量探测命令，确认额度是否恢复
3. **复活**：探测成功 → 自动执行你指定的 resume 命令（例如 `claude --continue -p continue` 接着跑任务）→ nanny 自己退出

全程不开浏览器、不用 computer use、不烧额外 token——每次探测只有一个最小请求。

## 安装

```powershell
git clone https://github.com/limpidwei/quota-nanny.git
pwsh quota-nanny\install.ps1   # 装到 ~/.local/bin（已在 PATH），生成 .cmd 全局命令
```

Linux / macOS / Termux 直接用 `bin/quota-nanny.sh`。

## 用法

### 手动拉起（知道已经撞墙了）

```powershell
quota-nanny.cmd -ProbeCommand "claude -p ping --max-turns 1" `
                -ResumeCommand "claude --continue -p 'continue the task'" `
                -IntervalSeconds 1800
```

```bash
quota-nanny.sh --probe "claude -p ping" \
               --resume "claude --continue -p continue" \
               --interval 1800
```

### 自动触发（盯着 agent 日志，撞墙自动拉起）

```powershell
quota-nanny-watch.cmd -LogFile "C:\path\to\agent-session.log" `
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

状态与日志在 `~/.quota-nanny/`：`nanny-<tag>.log`（探测记录）、`nanny-<tag>.ok`（恢复哨兵文件）。

## 设计原则

- **不用 GUI 自动化**：探测和续跑都是 CLI 调用，比 computer-use 方案便宜几个数量级
- **单实例**：同一 tag 只跑一个 nanny，重复触发会自己退出
- **自我了断**：额度恢复（或超过最大重试）即退出，不留残余进程

## 测试

仓库自带 mock LLM 和端到端测试（不碰真实 API）：

```powershell
pwsh tests\e2e-test.ps1      # 守护进程：常驻→定时重试→恢复自动退出
pwsh tests\watch-test.ps1    # watcher：日志出现 limit → 自动拉起 nanny
```

## English summary

A zero-GUI usage-limit watchdog for LLM agent CLIs. When your agent hits `usage limit` / 403 / 429, a background daemon probes every N minutes with a minimal request; once quota recovers it runs your resume command (e.g. re-invoking the agent with "continue") and exits. PowerShell + bash, single-instance, self-terminating. Ships with a mock LLM and e2e tests that never touch a real API.

## License

MIT
