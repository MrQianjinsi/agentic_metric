# Agentic Metric

[English](README.md)

本地化的 AI coding agent 指标监控工具。追踪 Claude Code、Codex、OpenCode、Qwen Code、VS Code (Copilot Chat) 等 agent 的 token 用量和成本，提供 TUI 仪表盘和 CLI 命令。

**支持平台：Linux 和 macOS。**

**所有数据完全存储在本地，使用过程不会联网。** 工具仅读取本机的 agent 数据文件（如 `~/.claude/`）和进程信息，不发送任何数据到外部服务器。

## 功能

- **实时监控** — 检测运行中的 agent 进程，增量解析 JSONL 会话数据
- **成本估算** — 基于各模型定价表计算 API 等效成本
- **今日概览** — 当天的 session 数、token 用量、花费汇总
- **历史趋势** — 每日 token/成本的 30 天趋势
- **TUI 仪表盘** — 终端图形界面，实时刷新（1 秒），含 token 堆叠图和趋势折线图
- **多 Agent 支持** — 插件架构，已支持 Claude Code、Codex、OpenCode、Qwen Code、VS Code，可扩展

## 数据来源

数据路径因平台而异，下表中 `$CONFIG` 和 `$DATA` 含义如下：

| | Linux | macOS |
|--|-------|-------|
| `$CONFIG` | `~/.config` | `~/Library/Application Support` |
| `$DATA` | `~/.local/share` | `~/Library/Application Support` |

| Agent | 数据路径 | 采集内容 |
|-------|---------|---------|
| Claude Code | `~/.claude/projects/` | JSONL 会话、token 用量、模型、分支 |
| Claude Code | `~/.claude/stats-cache.json` | 每日活动统计 |
| Codex | `~/.codex/sessions/` | JSONL 会话、token 用量、模型 |
| VS Code | `$CONFIG/Code/User/workspaceStorage/*/chatSessions/` | 聊天会话（JSON + JSONL）、token 用量（仅 JSONL）、模型 |
| VS Code | `$CONFIG/Code/User/globalStorage/emptyWindowChatSessions/` | 未打开项目时的聊天会话 |
| VS Code | 进程检测 | 运行状态、工作目录 |
| OpenCode | `$DATA/opencode/opencode.db` | SQLite 会话、消息、token 用量、模型 |
| OpenCode | 进程检测 | 运行状态、活跃会话匹配 |
| Qwen Code | `~/.qwen/projects/*/chats/` | JSONL 会话、token 用量、模型、分支 |
| Qwen Code | 进程检测 | 运行状态、工作目录 |

所有数据汇总存储在 `$DATA/agentic_metric/data.db`（SQLite）。

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
agentic-metric bar             # 单行摘要，用于状态栏集成
```

### 状态栏集成

`agentic-metric bar` 输出紧凑的单行摘要（如 `AM: $1.23 | 4.5M`），可嵌入 i3blocks、waybar、tmux、vim statusline 等状态栏。

**i3blocks / waybar：**

```ini
[agentic-metric]
command=agentic-metric bar
interval=60
```

**tmux：**

```tmux
set -g status-right '#(agentic-metric bar | head -1)'
set -g status-interval 60    # 每 60 秒刷新一次（默认 15 秒）
```

**vim / neovim statusline：**

```vim
set statusline+=%{system('agentic-metric\ bar\ \|\ head\ -1')}
" statusline 在光标移动、模式切换等事件时自动刷新
" 如需定时刷新，可添加 timer：
autocmd CursorHold * redrawstatus
set updatetime=60000          " 空闲 60 秒后触发 CursorHold
```

### TUI 快捷键

| 键 | 功能 |
|----|------|
| `q` | 退出 |
| `r` | 刷新数据 |
| `Tab` | 切换 Dashboard / History 标签页 |

## 各 Agent 统计口径差异

不同 agent 在本地暴露的数据详细程度不同：

| 字段 | Claude Code | Codex | VS Code (Copilot) | OpenCode | Qwen Code |
|------|:-----------:|:-----:|:-----------------:|:--------:|:---------:|
| 会话 ID | ✓ JSONL 文件 | ✓ JSONL 文件 | ✓ sessionId | ✓ session 表 | ✓ JSONL 文件 |
| 项目路径 | ✓ | ✓ | ✓ workspace.json URI | ✓ session.directory（启动目录） | ✓ |
| Git 分支 | ✓ | ✓ | ✗ 不存储 | ✗ 不存储 | ✓ |
| 模型名称 | ✓ | ✓ | ✓ result.details（如 "Claude Haiku 4.5 • 1x"） | ✓ message.modelID | ✓（通过 telemetry） |
| Input tokens | ✓ 逐条累加 | ✓ 累计值 | ◐ 仅 JSONL 格式 | ✓ 逐条累加 | ✓ 逐响应（telemetry） |
| Output tokens | ✓ 逐条累加 | ✓ 累计值 | ◐ 仅 JSONL 格式 | ✓ 逐条累加（含 reasoning） | ✓ 逐响应（telemetry） |
| Cache tokens | ✓ 读+写 | ✓ 仅读 | ✗ 不暴露 | ◐ 仅读（write 始终为 0） | ◐ 仅读（write 不暴露） |
| 用户轮次 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 消息总数 | ✓ user + assistant（排除 tool_result） | ✓ user + assistant | ✓ 轮次 × 2 | ✓ user + assistant | ✓ user + assistant |
| 首条/末条 prompt | ✓ | ✓ | ✓ message.text | ✓ 从 part 表提取 | ✓ 从 message.parts 提取 |
| 成本估算 | ✓ | ✓ | ◐ 仅在有 token 数据时可估算 | ◐ 全部为估算（上报 cost 始终为 0） | ✓（按 qwen3-coder-plus 定价） |
| 实时活跃状态 | ✓ PID + 会话文件精确匹配 | ✓ PID + 会话文件精确匹配 | ◐ 仅进程级检测 | ✓ PID + DB 会话匹配 | ✓ PID + 会话文件精确匹配 |

**主要差异说明：**

- **Claude Code 和 Codex** — 每个运行中的进程对应一个 JSONL 会话文件，文件内含唯一 session ID，因此可以精确匹配 live 进程和数据库会话。
- **VS Code (Copilot Chat)** — 存在两种存储格式：旧版 JSON（无 token 数据）和新版增量 JSONL（含 `result.usage`，包括 `promptTokens`/`completionTokens`）。Token 用量仅在 JSONL 格式的会话中可用。模型名称从 Copilot 的显示字符串（如 "GPT-4o • 1x"）提取并归一化为定价键。工作区路径支持本地（`file://`）、SSH 远程（`vscode-remote://ssh-remote+host`）和容器（`attached-container+...`）URI。
- **OpenCode** — 数据存储在本地 SQLite 数据库（`opencode.db`）。Token 数据按消息粒度记录，包含 `input`、`output`、`reasoning` 和 `cache.read`/`cache.write` 字段。Reasoning tokens 计入 output tokens（按 output 费率计费）。消息中的 `cost` 字段始终为 0，因此所有成本均通过定价表估算。`cache.write` 也始终为 0。
- **Qwen Code** — JSONL 布局与 Claude Code 类似，存储在 `~/.qwen/projects/<哈希路径>/chats/` 下。Token 数据来自 `system/ui_telemetry` 条目（`qwen-code.api_response`），而非 assistant 消息的 usage 字段。成本按 qwen3-coder-plus 定价估算。Qwen Code 默认使用免费 OAuth，实际费用可能为 $0。

## 不支持的 Agent

- **Cursor** — Cursor 自 2026 年 1 月左右（约 2.0.63+ 版本）起不再向本地 `state.vscdb` 数据库写入 token 用量数据（`tokenCount`），所有 `inputTokens`/`outputTokens` 值均为 0。Cursor 已将用量追踪迁移至服务端。由于本工具的设计原则是完全离线、不联网，无法通过网络 API 获取 Cursor 的用量数据，因此无法支持监测 Cursor 的用量。

## 隐私

- 不联网，不发送任何数据
- 不修改 agent 的配置或数据文件（只读）
- 所有统计数据存储在本地 SQLite 数据库
- 可随时删除数据目录清除所有数据（Linux: `~/.local/share/agentic_metric/`，macOS: `~/Library/Application Support/agentic_metric/`）
