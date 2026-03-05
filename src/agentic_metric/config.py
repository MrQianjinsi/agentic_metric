"""Configuration constants and paths."""

import platform
from pathlib import Path

_HOME = Path.home()
_IS_MAC = platform.system() == "Darwin"

# Platform-specific base directories
_APP_SUPPORT = _HOME / "Library" / "Application Support" if _IS_MAC else None

# Claude Code data paths
CLAUDE_HOME = _HOME / ".claude"
STATS_CACHE = CLAUDE_HOME / "stats-cache.json"
PROJECTS_DIR = CLAUDE_HOME / "projects"

# Codex CLI data paths
CODEX_HOME = _HOME / ".codex"
CODEX_SESSIONS_DIR = CODEX_HOME / "sessions"

# Cursor data paths
CURSOR_TRACKING_DB = _HOME / ".cursor" / "ai-tracking" / "ai-code-tracking.db"
CURSOR_STATE_DB = (
    _APP_SUPPORT / "Cursor" / "User" / "globalStorage" / "state.vscdb"
    if _IS_MAC
    else _HOME / ".config" / "Cursor" / "User" / "globalStorage" / "state.vscdb"
)

# OpenCode data paths
OPENCODE_DB = (
    _APP_SUPPORT / "opencode" / "opencode.db"
    if _IS_MAC
    else _HOME / ".local" / "share" / "opencode" / "opencode.db"
)

# VS Code (Copilot Chat) data paths
VSCODE_STORAGE_DIR = (
    _APP_SUPPORT / "Code" / "User" / "workspaceStorage"
    if _IS_MAC
    else _HOME / ".config" / "Code" / "User" / "workspaceStorage"
)
VSCODE_GLOBAL_CHAT_DIR = (
    _APP_SUPPORT / "Code" / "User" / "globalStorage" / "emptyWindowChatSessions"
    if _IS_MAC
    else _HOME / ".config" / "Code" / "User" / "globalStorage" / "emptyWindowChatSessions"
)

# Application data
DATA_DIR = (
    _APP_SUPPORT / "agentic_metric"
    if _IS_MAC
    else _HOME / ".local" / "share" / "agentic_metric"
)
DB_PATH = DATA_DIR / "data.db"

# Refresh intervals (seconds)
LIVE_REFRESH_INTERVAL = 1  # running sessions
DATA_SYNC_INTERVAL = 300  # history sync to sqlite
