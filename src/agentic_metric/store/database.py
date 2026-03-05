"""SQLite schema and CRUD operations."""

from __future__ import annotations

import sqlite3

from ..config import DATA_DIR, DB_PATH

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    agent_type TEXT NOT NULL,
    project_path TEXT,
    git_branch TEXT DEFAULT '',
    model TEXT DEFAULT '',
    message_count INTEGER DEFAULT 0,
    user_turns INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_creation_tokens INTEGER DEFAULT 0,
    estimated_cost_usd REAL DEFAULT 0,
    started_at TEXT,
    ended_at TEXT,
    first_prompt TEXT DEFAULT '',
    last_prompt TEXT DEFAULT '',
    summary TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class Database:
    def __init__(self, db_path: str | None = None) -> None:
        self._path = db_path or str(DB_PATH)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Add columns that may be missing in older databases."""
        cols = {
            r[1]
            for r in self._conn.execute("PRAGMA table_info(sessions)").fetchall()
        }
        if "last_prompt" not in cols:
            self._conn.execute(
                "ALTER TABLE sessions ADD COLUMN last_prompt TEXT DEFAULT ''"
            )

    def close(self) -> None:
        self._conn.close()

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    # ── Sync state ────────────────────────────────────────────────

    def get_sync_state(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM sync_state WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_sync_state(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO sync_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._conn.commit()

    # ── Session CRUD ──────────────────────────────────────────────

    def upsert_session(
        self,
        session_id: str,
        agent_type: str,
        *,
        project_path: str = "",
        git_branch: str = "",
        model: str = "",
        message_count: int = 0,
        user_turns: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
        started_at: str = "",
        ended_at: str = "",
        first_prompt: str = "",
        last_prompt: str = "",
        summary: str = "",
    ) -> None:
        self._conn.execute(
            """INSERT INTO sessions
                   (session_id, agent_type, project_path, git_branch, model,
                    message_count, user_turns, input_tokens, output_tokens,
                    cache_read_tokens, cache_creation_tokens, estimated_cost_usd,
                    started_at, ended_at, first_prompt, last_prompt, summary)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET
                   message_count = excluded.message_count,
                   user_turns = excluded.user_turns,
                   input_tokens = excluded.input_tokens,
                   output_tokens = excluded.output_tokens,
                   cache_read_tokens = excluded.cache_read_tokens,
                   cache_creation_tokens = excluded.cache_creation_tokens,
                   estimated_cost_usd = excluded.estimated_cost_usd,
                   ended_at = excluded.ended_at,
                   last_prompt = excluded.last_prompt,
                   summary = excluded.summary,
                   model = CASE WHEN excluded.model != '' THEN excluded.model ELSE sessions.model END,
                   project_path = CASE WHEN excluded.project_path != '' THEN excluded.project_path ELSE sessions.project_path END
            """,
            (
                session_id, agent_type, project_path, git_branch, model,
                message_count, user_turns, input_tokens, output_tokens,
                cache_read_tokens, cache_creation_tokens, estimated_cost_usd,
                started_at, ended_at, first_prompt, last_prompt, summary,
            ),
        )

    def commit(self) -> None:
        self._conn.commit()
