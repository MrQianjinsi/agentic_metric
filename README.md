# Agentic Metric

本地化的 AI coding agent 指标监控工具。追踪 Claude Code、Cursor 等 agent 的 token 用量和成本，提供 TUI 仪表盘、系统托盘和 CLI 命令。

**所有数据完全存储在本地，使用过程不会联网。** 工具仅读取本机的 agent 数据文件（如 `~/.claude/`）和进程信息，不发送任何数据到外部服务器。

## 功能

- **实时监控** — 检测运行中的 agent 进程，增量解析 JSONL 会话数据
- **成本估算** — 基于各模型定价表计算 API 等效成本
- **今日概览** — 当天的 session 数、token 用量、花费汇总
- **历史趋势** — 每日 token/成本的 30 天趋势
- **TUI 仪表盘** — 终端图形界面，实时刷新（1 秒），含 token 堆叠图和趋势折线图
- **系统托盘** — 驻留在系统托盘，右键菜单快速查看状态
- **多 Agent 支持** — 插件架构，已支持 Claude Code 和 Cursor，可扩展

## 数据来源

| Agent | 数据路径 | 采集内容 |
|-------|---------|---------|
| Claude Code | `~/.claude/projects/` | JSONL 会话、token 用量、模型、分支 |
| Claude Code | `~/.claude/stats-cache.json` | 每日活动统计 |
| Cursor | 进程检测 | 运行状态、工作目录 |

所有数据汇总存储在 `~/.local/share/agentic_metric/data.db`（SQLite）。

## 安装

```bash
pip install agentic-metric
```

### 可选依赖

Linux 系统托盘菜单需要 AppIndicator（大多数桌面发行版已预装）：

```bash
# Ubuntu/Debian
sudo apt install gir1.2-ayatanaappindicator3-0.1

# Fedora
sudo dnf install libayatana-appindicator-gtk3
```

## 使用

```bash
agentic-metric status          # 查看当前活跃的 agent
agentic-metric today           # 今日用量概览
agentic-metric history         # 历史趋势（默认 30 天）
agentic-metric history -d 7    # 最近 7 天
agentic-metric sync            # 强制同步数据到本地数据库
agentic-metric tui             # 启动 TUI 仪表盘
agentic-metric tray            # 启动系统托盘图标
```

### TUI 快捷键

| 键 | 功能 |
|----|------|
| `q` | 退出 |
| `r` | 刷新数据 |
| `Tab` | 切换 Dashboard / History 标签页 |

## 隐私

- 不联网，不发送任何数据
- 不修改 agent 的配置或数据文件（只读）
- 所有统计数据存储在本地 SQLite 数据库
- 可随时删除 `~/.local/share/agentic_metric/` 清除所有数据
