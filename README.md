# Agentic Metric

[中文文档](README-CN.md)

A local-only monitoring tool for AI coding agents. Track token usage and costs across Claude Code, Codex, OpenCode, Qwen Code, VS Code (Copilot Chat), and more — with a TUI dashboard and CLI.

**Supported platforms: Linux and macOS.**

**All data stays on your machine. No network requests, no telemetry, no data leaves your computer.** The tool only reads local agent data files (e.g. `~/.claude/`) and process info.

## Features

- **Live monitoring** — Detect running agent processes, incremental JSONL session parsing
- **Cost estimation** — Per-model pricing table, calculates API-equivalent costs
- **Today overview** — Sessions, token usage, and cost summary for the current day
- **Historical trends** — 30-day daily token/cost trends
- **TUI dashboard** — Terminal UI with 1-second live refresh, stacked token charts, and trend lines
- **Multi-agent** — Plugin architecture, supports Claude Code, Codex, OpenCode, Qwen Code, VS Code, extensible

## Agent Data Coverage

| Field | Claude Code | Codex | VS Code (Copilot) | OpenCode | Qwen Code |
|-------|:-----------:|:-----:|:-----------------:|:--------:|:---------:|
| Session ID | ✓ | ✓ | ✓ | ✓ | ✓ |
| Project path | ✓ | ✓ | ✓ | ✓ | ✓ |
| Git branch | ✓ | ✓ | ✗ | ✗ | ✓ |
| Model | ✓ | ✓ | ✓ | ✓ | ✓ |
| Input tokens | ✓ | ✓ | ✓¹ | ✓ | ✓ |
| Output tokens | ✓ | ✓ | ✓¹ | ✓ | ✓ |
| Cache tokens | ✓ | ✓³ | ✗ | ✓³ | ✓³ |
| User turns | ✓ | ✓ | ✓ | ✓ | ✓ |
| Message count | ✓ | ✓ | ✓ | ✓ | ✓ |
| First/last prompt | ✓ | ✓ | ✓ | ✓ | ✓ |
| Cost estimation | ✓ | ✓ | ✓¹ | ✓ | ✓ |
| Live active status | ✓ | ✓ | ✓² | ✓ | ✓ |

> ¹ VS Code legacy JSON sessions (older Copilot versions) do not contain token data; only newer JSONL sessions are supported.
> ² VS Code live status is process-level only; cannot match to a specific Copilot Chat session.
> ³ Cache read tokens only; cache write data is not exposed.

## Installation

```bash
pip install agentic-metric
```

## Usage

```bash
agentic-metric status          # Show currently active agents
agentic-metric today           # Today's usage overview
agentic-metric history         # Historical trends (default 30 days)
agentic-metric history -d 7    # Last 7 days
agentic-metric sync            # Force sync data to local database
agentic-metric tui             # Launch TUI dashboard
agentic-metric bar             # One-line summary for status bars
```

### Status Bar Integration

`agentic-metric bar` outputs a compact one-line summary (e.g. `AM: $1.23 | 4.5M`) for embedding into status bars like i3blocks, waybar, tmux, vim statusline, etc.

**i3blocks / waybar:**

```ini
[agentic-metric]
command=agentic-metric bar
interval=60
```

**tmux:**

```tmux
set -g status-right '#(agentic-metric bar | head -1)'
set -g status-interval 60    # refresh every 60 seconds (default 15)
```

**vim / neovim statusline:**

```vim
set statusline+=%{system('agentic-metric\ bar\ \|\ head\ -1')}
" statusline refreshes on cursor move, mode change, etc.
" to force a periodic refresh, add a timer:
autocmd CursorHold * redrawstatus
set updatetime=60000          " trigger CursorHold after 60s idle
```

### TUI Keybindings

| Key | Action |
|-----|--------|
| `q` | Quit |
| `r` | Refresh data |
| `Tab` | Switch Dashboard / History tab |

## Data Sources

Paths differ by platform. `$CONFIG` and `$DATA` refer to:

| | Linux | macOS |
|--|-------|-------|
| `$CONFIG` | `~/.config` | `~/Library/Application Support` |
| `$DATA` | `~/.local/share` | `~/Library/Application Support` |

| Agent | Path | Data |
|-------|------|------|
| Claude Code | `~/.claude/projects/` | JSONL sessions, token usage, model, branch |
| Claude Code | `~/.claude/stats-cache.json` | Daily activity stats |
| Codex | `~/.codex/sessions/` | JSONL sessions, token usage, model |
| VS Code | `$CONFIG/Code/User/workspaceStorage/*/chatSessions/` | Chat sessions (JSON + JSONL), token usage (JSONL only), model |
| VS Code | `$CONFIG/Code/User/globalStorage/emptyWindowChatSessions/` | Chat sessions without a project open |
| VS Code | Process detection | Running status, working directory |
| OpenCode | `$DATA/opencode/opencode.db` | SQLite sessions, messages, token usage, model |
| OpenCode | Process detection | Running status, active session matching |
| Qwen Code | `~/.qwen/projects/*/chats/` | JSONL sessions, token usage, model, branch |
| Qwen Code | Process detection | Running status, working directory |

All aggregated data is stored locally in `$DATA/agentic_metric/data.db` (SQLite).

## Unsupported Agents

- **Cursor** — Cursor stopped writing token usage data (`tokenCount`) to its local `state.vscdb` database around January 2026 (approximately version 2.0.63+). All `inputTokens`/`outputTokens` values are now zero. Cursor has moved usage tracking to a server-side system. Since this tool is designed to be fully offline with no network requests, there is no way to retrieve Cursor's usage data via network API, so monitoring Cursor usage is not supported.

## Privacy

- **Fully offline** — no network requests, no data sent anywhere
- **Read-only** — never modifies agent config or data files
- All stats stored in a local SQLite database
- Delete the data directory at any time to remove all data (`~/.local/share/agentic_metric/` on Linux, `~/Library/Application Support/agentic_metric/` on macOS)
