# Agentic Metric

[English](README.md)

本地化的 AI coding agent 指标监控工具。追踪 Claude Code、Codex、Cursor、OpenCode、VS Code (Copilot Chat) 等 agent 的 token 用量和成本，提供 TUI 仪表盘和 CLI 命令。

**所有数据完全存储在本地，使用过程不会联网。** 工具仅读取本机的 agent 数据文件（如 `~/.claude/`）和进程信息，不发送任何数据到外部服务器。

## 功能

- **实时监控** — 检测运行中的 agent 进程，增量解析 JSONL 会话数据
- **成本估算** — 基于各模型定价表计算 API 等效成本
- **今日概览** — 当天的 session 数、token 用量、花费汇总
- **历史趋势** — 每日 token/成本的 30 天趋势
- **TUI 仪表盘** — 终端图形界面，实时刷新（1 秒），含 token 堆叠图和趋势折线图
- **多 Agent 支持** — 插件架构，已支持 Claude Code 和 Cursor，可扩展

## 数据来源

| Agent | 数据路径 | 采集内容 |
|-------|---------|---------|
| Claude Code | `~/.claude/projects/` | JSONL 会话、token 用量、模型、分支 |
| Claude Code | `~/.claude/stats-cache.json` | 每日活动统计 |
| Cursor | `~/.config/Cursor/User/globalStorage/state.vscdb` | Composer 会话、token 用量、模型 |
| Cursor | 进程检测 | 运行状态、工作目录 |
| Codex | `~/.codex/sessions/` | JSONL 会话、token 用量、模型 |
| VS Code | `~/.config/Code/User/workspaceStorage/*/chatSessions/` | 聊天会话（JSON + JSONL）、token 用量（仅 JSONL）、模型 |
| VS Code | `~/.config/Code/User/globalStorage/emptyWindowChatSessions/` | 空窗口聊天会话 |
| VS Code | 进程检测 | 运行状态、工作目录 |
| OpenCode | `~/.local/share/opencode/opencode.db` | SQLite 会话、消息、token 用量、模型 |
| OpenCode | 进程检测 | 运行状态、活跃会话匹配 |

所有数据汇总存储在 `~/.local/share/agentic_metric/data.db`（SQLite）。

## 安装

```bash
pip install agentic-metric
```

## 使用

```bash
agentic-metric status          # 查看当前活跃的 agent
agentic-metric today           # 今日用量概览
agentic-metric history         # 历史趋势（默认 30 天）
agentic-metric history -d 7    # 最近 7 天
agentic-metric sync            # 强制同步数据到本地数据库
agentic-metric tui             # 启动 TUI 仪表盘
```

### TUI 快捷键

| 键 | 功能 |
|----|------|
| `q` | 退出 |
| `r` | 刷新数据 |
| `Tab` | 切换 Dashboard / History 标签页 |

## 各 Agent 统计口径差异

不同 agent 在本地暴露的数据详细程度不同：

| 字段 | Claude Code | Codex | Cursor | VS Code (Copilot) | OpenCode |
|------|:-----------:|:-----:|:------:|:-----------------:|:--------:|
| 会话 ID | ✓ JSONL 文件 | ✓ JSONL 文件 | ✓ composerId | ✓ sessionId | ✓ session 表 |
| 项目路径 | ✓ | ✓ | ◐ 部分（从 bubble 或 conversationState 提取） | ✓ workspace.json URI | ✓ session.directory（启动目录） |
| Git 分支 | ✓ | ✓ | ✗ 不存储 | ✗ 不存储 | ✗ 不存储 |
| 模型名称 | ✓ | ✓ | ✓ 但 "default" 模式不记录实际模型 | ✓ result.details（如 "Claude Haiku 4.5 • 1x"） | ✓ message.modelID |
| Input tokens | ✓ 逐条累加 | ✓ 累计值 | ◐ 约 75% 会话有数据 | ◐ 仅 JSONL 格式 | ✓ 逐条累加 |
| Output tokens | ✓ 逐条累加 | ✓ 累计值 | ◐ 约 75% 会话有数据 | ◐ 仅 JSONL 格式 | ✓ 逐条累加（含 reasoning） |
| Cache tokens | ✓ 读+写 | ✓ 仅读 | ✗ 不暴露 | ✗ 不暴露 | ◐ 仅读（write 始终为 0） |
| 用户轮次 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 消息总数 | ✓ 所有消息 | ✓ 仅 AI 回复 | ✓ 所有消息 | ✓ 轮次 × 2 | ✓ 所有消息 |
| 首条/末条 prompt | ✓ | ✓ | ✓ 从 bubble text 提取 | ✓ message.text | ✓ 从 part 表提取 |
| 成本估算 | ✓ | ✓ | ◐ 仅在有 token 数据时可估算 | ◐ 仅在有 token 数据时可估算 | ◐ 全部为估算（上报 cost 始终为 0） |
| 实时活跃状态 | ✓ PID + 会话文件精确匹配 | ✓ PID + 会话文件精确匹配 | ◐ 仅进程级检测（标记最新会话为活跃） | ◐ 仅进程级检测 | ✓ PID + DB 会话匹配 |

**主要差异说明：**

- **Claude Code 和 Codex** — 每个运行中的进程对应一个 JSONL 会话文件，文件内含唯一 session ID，因此可以精确匹配 live 进程和数据库会话。
- **Cursor** — 实时检测只能获取进程 PID，而历史会话使用 `state.vscdb` 中的 composer UUID。两者无法关联，因此仅在 Cursor 进程运行时将最新会话标记为活跃。
- **Token 覆盖率** — Cursor 并非对所有会话都记录 token 消耗，老版本会话和部分 "default" 模型会话的 token 为零。Cache token 细分（读/写）不可用。
- **模型名称** — Cursor 的 "default" 模型设置不记录后端实际使用的模型，这类会话在模型列显示为 `default`。
- **VS Code (Copilot Chat)** — 存在两种存储格式：旧版 JSON（无 token 数据）和新版增量 JSONL（含 `result.usage`，包括 `promptTokens`/`completionTokens`）。Token 用量仅在 JSONL 格式的会话中可用。模型名称从 Copilot 的显示字符串（如 "GPT-4o • 1x"）提取并归一化为定价键。工作区路径支持本地（`file://`）、SSH 远程（`vscode-remote://ssh-remote+host`）和容器（`attached-container+...`）URI。
- **OpenCode** — 数据存储在本地 SQLite 数据库（`opencode.db`）。Token 数据按消息粒度记录，包含 `input`、`output`、`reasoning` 和 `cache.read`/`cache.write` 字段。Reasoning tokens 计入 output tokens（按 output 费率计费）。消息中的 `cost` 字段始终为 0，因此所有成本均通过定价表估算。`cache.write` 也始终为 0。

## 隐私

- 不联网，不发送任何数据
- 不修改 agent 的配置或数据文件（只读）
- 所有统计数据存储在本地 SQLite 数据库
- 可随时删除 `~/.local/share/agentic_metric/` 清除所有数据
