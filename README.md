# Agentic Metric

[中文文档](README-CN.md)

A local-only monitoring tool for AI coding agents. Track token usage and costs across Claude Code, Codex, Cursor, OpenCode, VS Code (Copilot Chat), and more — with a TUI dashboard and CLI.

**All data stays on your machine. No network requests, no telemetry, no data leaves your computer.** The tool only reads local agent data files (e.g. `~/.claude/`) and process info.

## Features

- **Live monitoring** — Detect running agent processes, incremental JSONL session parsing
- **Cost estimation** — Per-model pricing table, calculates API-equivalent costs
- **Today overview** — Sessions, token usage, and cost summary for the current day
- **Historical trends** — 30-day daily token/cost trends
- **TUI dashboard** — Terminal UI with 1-second live refresh, stacked token charts, and trend lines
- **Multi-agent** — Plugin architecture, supports Claude Code and Cursor, extensible

## Data Sources

| Agent | Path | Data |
|-------|------|------|
| Claude Code | `~/.claude/projects/` | JSONL sessions, token usage, model, branch |
| Claude Code | `~/.claude/stats-cache.json` | Daily activity stats |
| Cursor | `~/.config/Cursor/User/globalStorage/state.vscdb` | Composer sessions, token usage, model |
| Cursor | Process detection | Running status, working directory |
| Codex | `~/.codex/sessions/` | JSONL sessions, token usage, model |
| VS Code | `~/.config/Code/User/workspaceStorage/*/chatSessions/` | Chat sessions (JSON + JSONL), token usage (JSONL only), model |
| VS Code | `~/.config/Code/User/globalStorage/emptyWindowChatSessions/` | Empty-window chat sessions |
| VS Code | Process detection | Running status, working directory |
| OpenCode | `~/.local/share/opencode/opencode.db` | SQLite sessions, messages, token usage, model |
| OpenCode | Process detection | Running status, active session matching |

All aggregated data is stored locally in `~/.local/share/agentic_metric/data.db` (SQLite).

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
```

### TUI Keybindings

| Key | Action |
|-----|--------|
| `q` | Quit |
| `r` | Refresh data |
| `Tab` | Switch Dashboard / History tab |

## Agent Data Coverage

Different agents expose different levels of local data. Here's what's available for each:

| Field | Claude Code | Codex | Cursor | VS Code (Copilot) | OpenCode |
|-------|:-----------:|:-----:|:------:|:-----------------:|:--------:|
| Session ID | ✓ JSONL | ✓ JSONL | ✓ composerId | ✓ sessionId | ✓ session table |
| Project path | ✓ JSONL | ✓ JSONL | ◐ partial (from bubble or conversationState) | ✓ workspace.json URI | ✓ session.directory (launch cwd) |
| Git branch | ✓ JSONL | ✓ JSONL | ✗ not stored | ✗ not stored | ✗ not stored |
| Model | ✓ JSONL | ✓ JSONL | ✓ modelConfig / bubble modelInfo | ✓ result.details (e.g. "Claude Haiku 4.5 • 1x") | ✓ message.modelID |
| Input tokens | ✓ per-message | ✓ cumulative | ◐ ~75% of sessions | ◐ JSONL format only | ✓ per-message |
| Output tokens | ✓ per-message | ✓ cumulative | ◐ ~75% of sessions | ◐ JSONL format only | ✓ per-message (includes reasoning) |
| Cache tokens | ✓ read + write | ✓ read only | ✗ not exposed | ✗ not exposed | ◐ read only (write always 0) |
| User turns | ✓ | ✓ | ✓ | ✓ | ✓ |
| Message count | ✓ all messages | ✓ AI replies only | ✓ all messages | ✓ turns × 2 | ✓ all messages |
| First/last prompt | ✓ | ✓ | ✓ from bubble text | ✓ message.text | ✓ from part table |
| Cost estimation | ✓ | ✓ | ◐ only when tokens available | ◐ only when tokens available | ◐ estimated only (reported cost always 0) |
| Live active status | ✓ PID + session file match | ✓ PID + session file match | ◐ process-level only (latest session marked active) | ◐ process-level only | ✓ PID + DB session match |

**Key differences:**

- **Claude Code & Codex** — Each running process maps to a JSONL session file with a unique session ID. This allows precise matching between live processes and DB sessions for accurate active status.
- **Cursor** — Live detection only sees the process PID, while historical sessions use composer UUIDs from `state.vscdb`. There is no way to link a running Cursor process to a specific composer session, so the most recent session is marked active when the process is running.
- **Token coverage** — Cursor does not record token counts for all sessions. Older sessions and some "default" model sessions have zero tokens. Cache token breakdown (read/write) is not available.
- **Model name** — Cursor's "default" model setting doesn't record which model was actually used on the backend. These sessions show `default` in the model column.
- **VS Code (Copilot Chat)** — Has two storage formats: legacy JSON (older sessions, no token data) and newer incremental JSONL (with `result.usage` containing `promptTokens`/`completionTokens`). Token usage is only available for sessions stored in JSONL format. Model names are extracted from Copilot's display strings (e.g. "GPT-4o • 1x") and normalized to pricing keys. Workspace paths support local (`file://`), SSH remote (`vscode-remote://ssh-remote+host`), and container (`attached-container+...`) URIs.
- **OpenCode** — Stores all data in a local SQLite database (`opencode.db`). Token data is per-message with `input`, `output`, `reasoning`, and `cache.read`/`cache.write` fields. Reasoning tokens are counted as output tokens (billed at output rate). The `cost` field in messages is always 0, so all costs are estimated using the pricing table. `cache.write` is also always 0.

## Privacy

- **Fully offline** — no network requests, no data sent anywhere
- **Read-only** — never modifies agent config or data files
- All stats stored in a local SQLite database
- Delete `~/.local/share/agentic_metric/` at any time to remove all data
