"""Configuration constants and paths."""

from pathlib import Path

# Claude Code data paths
CLAUDE_HOME = Path.home() / ".claude"
STATS_CACHE = CLAUDE_HOME / "stats-cache.json"
PROJECTS_DIR = CLAUDE_HOME / "projects"

# Cursor data paths
CURSOR_TRACKING_DB = Path.home() / ".cursor" / "ai-tracking" / "ai-code-tracking.db"

# Application data
DATA_DIR = Path.home() / ".local" / "share" / "agentic_metric"
DB_PATH = DATA_DIR / "data.db"

# Refresh intervals (seconds)
LIVE_REFRESH_INTERVAL = 1  # running sessions
DATA_SYNC_INTERVAL = 300  # history sync to sqlite
