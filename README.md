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

## Agent Data Coverage

Different agents expose different levels of local data. Here's what's available for each:

| Field | Claude Code | Codex | VS Code (Copilot) | OpenCode | Qwen Code |
|-------|:-----------:|:-----:|:-----------------:|:--------:|:---------:|
| Session ID | ✓ JSONL | ✓ JSONL | ✓ sessionId | ✓ session table | ✓ JSONL |
| Project path | ✓ JSONL | ✓ JSONL | ✓ workspace.json URI | ✓ session.directory (launch cwd) | ✓ JSONL |
| Git branch | ✓ JSONL | ✓ JSONL | ✗ not stored | ✗ not stored | ✓ JSONL |
| Model | ✓ JSONL | ✓ JSONL | ✓ result.details (e.g. "Claude Haiku 4.5 • 1x") | ✓ message.modelID | ✓ JSONL (via telemetry) |
| Input tokens | ✓ per-message | ✓ cumulative | ◐ JSONL format only | ✓ per-message | ✓ per-response (telemetry) |
| Output tokens | ✓ per-message | ✓ cumulative | ◐ JSONL format only | ✓ per-message (includes reasoning) | ✓ per-response (telemetry) |
| Cache tokens | ✓ read + write | ✓ read only | ✗ not exposed | ◐ read only (write always 0) | ◐ read only (write not exposed) |
| User turns | ✓ | ✓ | ✓ | ✓ | ✓ |
| Message count | ✓ user + assistant (excl. tool_result) | ✓ user + assistant | ✓ turns × 2 | ✓ user + assistant | ✓ user + assistant |
| First/last prompt | ✓ | ✓ | ✓ message.text | ✓ from part table | ✓ from message.parts |
| Cost estimation | ✓ | ✓ | ◐ only when tokens available | ◐ estimated only (reported cost always 0) | ✓ (qwen3-coder-plus pricing) |
| Live active status | ✓ PID + session file match | ✓ PID + session file match | ◐ process-level only | ✓ PID + DB session match | ✓ PID + session file match |

**Key differences:**

- **Claude Code & Codex** — Each running process maps to a JSONL session file with a unique session ID. This allows precise matching between live processes and DB sessions for accurate active status.
- **VS Code (Copilot Chat)** — Has two storage formats: legacy JSON (older sessions, no token data) and newer incremental JSONL (with `result.usage` containing `promptTokens`/`completionTokens`). Token usage is only available for sessions stored in JSONL format. Model names are extracted from Copilot's display strings (e.g. "GPT-4o • 1x") and normalized to pricing keys. Workspace paths support local (`file://`), SSH remote (`vscode-remote://ssh-remote+host`), and container (`attached-container+...`) URIs.
- **OpenCode** — Stores all data in a local SQLite database (`opencode.db`). Token data is per-message with `input`, `output`, `reasoning`, and `cache.read`/`cache.write` fields. Reasoning tokens are counted as output tokens (billed at output rate). The `cost` field in messages is always 0, so all costs are estimated using the pricing table. `cache.write` is also always 0.
- **Qwen Code** — JSONL layout similar to Claude Code, stored under `~/.qwen/projects/<hashed-path>/chats/`. Token data comes from `system/ui_telemetry` entries (`qwen-code.api_response`) rather than assistant message usage fields. Costs are estimated using qwen3-coder-plus pricing. Qwen Code uses free OAuth by default, so actual costs may be $0.

## Unsupported Agents

- **Cursor** — Cursor stopped writing token usage data (`tokenCount`) to its local `state.vscdb` database around January 2026 (approximately version 2.0.63+). All `inputTokens`/`outputTokens` values are now zero. Cursor has moved usage tracking to a server-side system. Since this tool is designed to be fully offline with no network requests, there is no way to retrieve Cursor's usage data via network API, so monitoring Cursor usage is not supported.

## Privacy

- **Fully offline** — no network requests, no data sent anywhere
- **Read-only** — never modifies agent config or data files
- All stats stored in a local SQLite database
- Delete the data directory at any time to remove all data (`~/.local/share/agentic_metric/` on Linux, `~/Library/Application Support/agentic_metric/` on macOS)
