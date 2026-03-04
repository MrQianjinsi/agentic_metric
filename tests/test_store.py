"""Tests for store module."""

import sqlite3
import tempfile
from pathlib import Path

from agentic_metric.store.database import Database
from agentic_metric.store.aggregator import get_today_overview, get_daily_trends


def _make_db() -> Database:
    """Create an in-memory database for testing."""
    tmp = tempfile.mktemp(suffix=".db")
    return Database(db_path=tmp)


def test_database_creation():
    db = _make_db()
    # Check tables exist
    tables = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {r["name"] for r in tables}
    assert "sessions" in names
    assert "daily_stats" in names
    assert "model_daily_usage" in names
    assert "sync_state" in names
    db.close()


def test_upsert_session():
    db = _make_db()
    db.upsert_session(
        "s1", "claude_code",
        project_path="/home/test/project",
        input_tokens=1000,
        output_tokens=500,
    )
    db.commit()

    row = db.conn.execute("SELECT * FROM sessions WHERE session_id = 's1'").fetchone()
    assert row is not None
    assert row["agent_type"] == "claude_code"
    assert row["input_tokens"] == 1000

    # Upsert updates
    db.upsert_session("s1", "claude_code", input_tokens=2000, output_tokens=1000)
    db.commit()
    row = db.conn.execute("SELECT * FROM sessions WHERE session_id = 's1'").fetchone()
    assert row["input_tokens"] == 2000
    db.close()


def test_upsert_daily_stats():
    db = _make_db()
    db.upsert_daily_stats("2025-01-01", "claude_code", session_count=5, message_count=50)
    db.commit()

    row = db.conn.execute(
        "SELECT * FROM daily_stats WHERE date = '2025-01-01' AND agent_type = 'claude_code'"
    ).fetchone()
    assert row["session_count"] == 5
    assert row["message_count"] == 50
    db.close()


def test_sync_state():
    db = _make_db()
    assert db.get_sync_state("test_key") is None
    db.set_sync_state("test_key", "test_value")
    assert db.get_sync_state("test_key") == "test_value"
    db.set_sync_state("test_key", "updated")
    assert db.get_sync_state("test_key") == "updated"
    db.close()


def test_today_overview_empty():
    db = _make_db()
    overview = get_today_overview(db)
    assert overview.session_count == 0
    assert overview.total_tokens == 0
    db.close()


def test_daily_trends():
    db = _make_db()
    db.upsert_daily_stats("2025-01-01", "claude_code", session_count=3, input_tokens=10000)
    db.upsert_daily_stats("2025-01-02", "claude_code", session_count=5, input_tokens=20000)
    db.commit()

    trends = get_daily_trends(db, days=365 * 10)
    assert len(trends) == 2
    assert trends[0].date == "2025-01-01"
    assert trends[1].input_tokens == 20000
    db.close()
