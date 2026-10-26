# 429-wait Roadmap

## 定位

一站式 CLI agent 额度恢复工具。装一次，无感跟随 agent 启动，撞墙自动等候+恢复。

## 触发架构

**Shim 优先，Hook 可选优化。**

Shim 是通用方案：安装时注入 wrapper，用户照常敲 `claude` / `codex` / `aider`，实际走 429-wait 包裹。agent 撞墙退出 → 429-wait 自动等候 → 恢复后重新拉起。覆盖所有 CLI agent，不依赖任何 agent 自身的 hook 机制。

Hook（如 Claude Code StopFailure）是可选加速：零延迟触发，但只有个别 agent 支持，不通用。

GUI agent（DeepSeek Harness、WorkBuddy 等）列后续调研，MVP 不做。

---

## Phase 1 — Shim 框架 + Claude Code 适配（MVP）

- [x] 1.1 shim wrapper 核心逻辑（`bin/429-wait-shim.py`）：透传 agent 命令 → 捕获退出码 + stderr → 匹配限流特征 → 探测 API → 恢复后重新拉起 agent
- [x] 1.2 适配器配置格式（TOML，每个 agent 一个）：agent 命令名、限流退出码/stderr 正则、HTTP 探测、恢复命令模板
- [x] 1.3 Claude Code / Codex / Aider 适配器（`adapters/*.toml`）
- [x] 1.4 install 机制：`install.ps1`（Windows）+ `install.sh`（macOS/Linux），生成 shim 到 PATH，manifest 支持 uninstall
- [x] 1.5 e2e 测试（`tests/shim-e2e.py`）：mock agent 撞墙 → shim 捕获 → 探测 429x2→200 → 重新拉起 → 成功

## Phase 2 — 更多 agent 适配器

- [ ] 2.1 调研各 CLI agent 撞墙行为：退出码、stderr、API endpoint
  - Codex CLI
  - Aider
  - （其他按用户反馈加）
- [ ] 2.2 每个 agent 写适配器配置 + e2e mock 测试
- [ ] 2.3 shim 自动检测 agent 名，加载对应适配器

## Phase 3 — 产品化

- [ ] 3.1 `429-wait install --agent claude-code,codex` 一键注入
- [ ] 3.2 `429-wait status` 查看 shim 状态、等候状态
- [ ] 3.3 `429-wait uninstall` 干净还原
- [ ] 3.4 跨平台验证：Windows / macOS / Linux / Termux
- [ ] 3.5 文档补充：探针成本量化、v1/v2 关系明确（v2 是主线，v1 遗留 fallback）

## Phase 4 — 跨平台构建 & 分发

- [ ] 4.1 三平台独立包，GitHub Release 各出一个：
  - `429-wait-windows.zip` — .cmd shim + .py 脚本 + install.ps1
  - `429-wait-macos.tar.gz` — shell shim + .py 脚本 + install.sh
  - `429-wait-linux.tar.gz` — shell shim + .py 脚本 + install.sh
- [ ] 4.2 每个平台的 install 脚本负责：放 shim 到 PATH、注册适配器、验证 Python 可用
- [ ] 4.3 PyPI 发包：`pip install 429-wait`（跨平台，自动检测 OS 放对应 shim）
- [ ] 4.4 README 重写：按平台 × agent 分栏 quick start
- [ ] 4.5 更新宣发素材（突出"装完就忘，自动跟随"定位）
- [ ] 4.6 GitHub Release + tag（CI 自动打三平台包）

## 可选优化（非 MVP）

- [ ] Claude Code StopFailure hook 集成 — 零延迟触发，shim 已经能用，这是锦上添花
- [ ] Windows pid 守卫改用 tasklist/psutil 替代 os.kill(pid, 0)
- [x] install.sh for Linux/macOS（已实现）

---

## 不做（MVP 范围外）

- GUI agent 适配（DeepSeek Harness、ZCode、WorkBuddy）— 需要常驻进程 + 进程监控，工程量大，用户少
- WorkBuddy 积分制 — 机制完全不同（每天领积分），不是 429 限流
- 日志尾随模式 — 每个 agent 日志格式不同，维护成本高，shim 能覆盖同样场景
