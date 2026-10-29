# 429-wait Roadmap

## 定位

一站式 CLI agent 额度恢复工具：真实事件触发、每会话守候、恢复后接续正确上下文，并保留用户在原对话中的输出和控制权。

## 当前架构

**Claude Code：终端监督器 + StopFailure + probe-only + 原窗口同会话恢复。**

- `429-wait-terminal.py` 持有原 stdin/stdout 和 Claude 子进程。
- 最终429后，Hook 只写当前窗口专属事件；原 TUI 在等待期间保持可见。
- 探针恢复且状态稳定后，监督器停止空闲旧进程，在原终端执行 `--resume 同session_id 继续`。
- 用户手动继续、退出或状态无法确认时，不强制重启。
- 非监督会话才使用后台 fork 兜底。

**Codex / Aider：保留旧 shim。** 该路径仍依赖进程退出与 stderr，不能套用到 Claude TUI。

## Phase 1 — 真实机制与探针

- [x] 直接 HTTP 探针，避免 CLI 内部重试与微型探针假恢复
- [x] 真实会话确认初次请求 + 10 次重试后结束本轮、TUI 不退出
- [x] 本地假429验证 StopFailure payload
- [x] 后台 fork 全链路验证
- [x] 真实交互式 TUI 同窗口验证：原session_id记录出现恢复文本

## Phase 2 — 同窗口恢复主线

- [x] 每窗口 supervisor token 与 Hook 原子事件
- [x] 等待期间保留原 TUI，手动继续/退出取消自动恢复
- [x] 探针成功后停止旧进程，原窗口 `--resume 同session_id 继续`
- [x] 保留配置参数，过滤初始提示与 session 控制参数
- [x] 双窗口、重复事件、二次429、探针失败自动化测试
- [ ] 下一次自然生产 TUI 429 现场复核
- [ ] 带工具调用的同窗口恢复权限行为实测（不默认提权）
- [ ] 活动子 Agent 场景的进一步覆盖

## Phase 3 — 安装与兼容性

- [x] settings 幂等合并，保留其他 hooks/settings
- [x] Windows / Unix 监督器 wrapper 与安全升级、卸载
- [x] 隔离安装、升级、重复安装与卸载测试
- [x] 本机默认切换到同窗口监督器
- [ ] 更多 Claude Code 版本与 macOS/Linux 实机验证
- [ ] `429-wait status` 统一查看活动守候与恢复结果

## Phase 4 — 分发

- [ ] Windows / macOS / Linux 包与 Release
- [ ] PyPI 分发评估
- [ ] 宣发素材更新为原窗口、原会话恢复

## 后续可选

- 共享探测协调器，减少多窗口同时等待时的重复探针
- 守候状态显示与恢复完成通知
- 其他支持失败 Hook 的 Agent 适配

## 不做

- 通过 GUI 自动化向原 TUI“按继续”作为主线
- 用进程退出检测覆盖不会退出的交互式 Claude
- 为恢复默认增加提权参数
- 在用户手动继续或退出后强制抢回终端
