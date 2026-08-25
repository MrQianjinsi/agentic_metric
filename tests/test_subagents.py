"""Tests for Claude Code subagent (Task tool) session collection.

Claude Code writes subagent transcripts to
``<project>/<session-id>/subagents/*.jsonl``. Those files are separate from the
parent transcript and carry the PARENT's ``sessionId`` in every entry, which is
what makes them easy to collect wrongly:

* a non-recursive glob misses them entirely, and
* keying a row on the ``sessionId`` inside them makes every subagent of a
  session overwrite both each other and the parent row.
"""

import json
import tempfile
from datetime import datetime
from pathlib import Path

from agentic_metric.store.database import Database
from agentic_metric.store.aggregator import get_today_sessions


def _make_db() -> Database:
    return Database(db_path=tempfile.mktemp(suffix=".db"))


def _write_jsonl(path: Path, *, session_id: str, model: str, cwd: str,
                 out_tokens: int, turns: int = 1) -> None:
    """Write a minimal transcript the collector can parse."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = "2025-01-01T10:00:00.000Z"
    lines = []
    for _ in range(turns):
        lines.append({
            "type": "user", "sessionId": session_id, "cwd": cwd, "timestamp": ts,
            "message": {"role": "user", "content": "hello"},
        })
        lines.append({
            "type": "assistant", "sessionId": session_id, "cwd": cwd, "timestamp": ts,
            "message": {
                "role": "assistant", "model": model,
                "usage": {"input_tokens": 10, "output_tokens": out_tokens,
                          "cache_read_input_tokens": 0,
                          "cache_creation_input_tokens": 0},
            },
        })
    with open(path, "w") as f:
        for entry in lines:
            f.write(json.dumps(entry) + "\n")


def _fake_projects(tmp: Path, monkeypatch) -> Path:
    """Point the collector at a throwaway PROJECTS_DIR."""
    projects = tmp / "projects"
    projects.mkdir(parents=True, exist_ok=True)
    import agentic_metric.collectors.claude_code as cc
    monkeypatch.setattr(cc, "PROJECTS_DIR", projects)
    return projects


def _sync(db) -> None:
    from agentic_metric.collectors.claude_code import ClaudeCodeCollector
    ClaudeCodeCollector()._sync_jsonl_tokens(db)
    db.commit()


# ── collection ────────────────────────────────────────────────────────────


def test_subagent_transcripts_are_collected(tmp_path, monkeypatch):
    """A nested subagents/ transcript must produce its own row."""
    projects = _fake_projects(tmp_path, monkeypatch)
    proj = projects / "-tmp-demo"
    parent_id = "11111111-2222-3333-4444-555555555555"

    _write_jsonl(proj / f"{parent_id}.jsonl",
                 session_id=parent_id, model="claude-opus-5",
                 cwd="/tmp/demo", out_tokens=100)
    _write_jsonl(proj / parent_id / "subagents" / "agent-worker-abc123.jsonl",
                 session_id=parent_id, model="claude-sonnet-5",
                 cwd="/tmp/demo", out_tokens=40)

    db = _make_db()
    _sync(db)

    rows = {r["session_id"]: r for r in
            db.conn.execute("SELECT * FROM sessions").fetchall()}
    assert parent_id in rows, "parent session missing"
    assert "agent-worker-abc123" in rows, "subagent transcript was not collected"

    sub = rows["agent-worker-abc123"]
    assert sub["model"] == "claude-sonnet-5"
    assert sub["output_tokens"] == 40
    assert sub["parent_session_id"] == parent_id
    db.close()


def test_subagents_do_not_overwrite_each_other(tmp_path, monkeypatch):
    """Every entry carries the parent's sessionId; rows must still be distinct."""
    projects = _fake_projects(tmp_path, monkeypatch)
    proj = projects / "-tmp-demo"
    parent_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    _write_jsonl(proj / f"{parent_id}.jsonl",
                 session_id=parent_id, model="claude-opus-5",
                 cwd="/tmp/demo", out_tokens=100)
    for name, tokens in (("agent-a-1", 11), ("agent-b-2", 22), ("agent-c-3", 33)):
        _write_jsonl(proj / parent_id / "subagents" / f"{name}.jsonl",
                     session_id=parent_id, model="claude-sonnet-5",
                     cwd="/tmp/demo", out_tokens=tokens)

    db = _make_db()
    _sync(db)

    subs = db.conn.execute(
        "SELECT session_id, output_tokens FROM sessions WHERE parent_session_id = ?",
        (parent_id,),
    ).fetchall()
    assert len(subs) == 3, "subagents collapsed into one row"
    assert sorted(r["output_tokens"] for r in subs) == [11, 22, 33]

    parent = db.conn.execute(
        "SELECT output_tokens, parent_session_id FROM sessions WHERE session_id = ?",
        (parent_id,),
    ).fetchone()
    assert parent["output_tokens"] == 100, "parent row was overwritten by a subagent"
    assert parent["parent_session_id"] == ""
    db.close()


# ── schema ────────────────────────────────────────────────────────────────


def test_migration_adds_parent_session_id():
    """An older database gains the column without losing rows."""
    path = tempfile.mktemp(suffix=".db")
    import sqlite3
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE sessions (session_id TEXT PRIMARY KEY, agent_type TEXT NOT NULL,"
        " model TEXT DEFAULT '', started_at TEXT)"
    )
    conn.execute("INSERT INTO sessions VALUES ('old', 'claude_code', 'x', '2025-01-01T00:00:00')")
    conn.commit()
    conn.close()

    db = Database(db_path=path)
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(sessions)").fetchall()}
    assert "parent_session_id" in cols
    assert db.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    db.close()


# ── display rollup ────────────────────────────────────────────────────────


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%dT10:00:00")


def _seed(db, parent_model: str, child_models: list[str]) -> str:
    parent_id = "parent-1"
    db.upsert_session(parent_id, "claude_code", model=parent_model,
                      output_tokens=100, estimated_cost_usd=1.0,
                      started_at=_today())
    for i, m in enumerate(child_models):
        db.upsert_session(f"agent-{i}", "claude_code", model=m,
                          output_tokens=10, estimated_cost_usd=0.5,
                          started_at=_today(), parent_session_id=parent_id)
    db.commit()
    return parent_id


def test_rollup_sums_tokens_and_cost():
    db = _make_db()
    _seed(db, "claude-opus-5", ["claude-sonnet-5", "claude-sonnet-5"])
    rows = get_today_sessions(db)
    assert len(rows) == 1, "subagents were listed instead of folded"
    row = rows[0]
    assert row["output_tokens"] == 120
    assert row["estimated_cost_usd"] == 2.0
    assert row["subagent_count"] == 2
    db.close()


def test_rollup_labels_distinct_child_models():
    db = _make_db()
    _seed(db, "claude-fable-5", ["claude-opus-5"] * 3)
    assert get_today_sessions(db)[0]["model"] == "claude-fable-5 +3x claude-opus-5"
    db.close()


def test_rollup_keeps_children_sharing_the_parent_model():
    """A subagent on the parent's model costs the same and must stay visible."""
    db = _make_db()
    _seed(db, "claude-opus-5", ["claude-opus-5"] * 3)
    row = get_today_sessions(db)[0]
    assert row["model"] == "claude-opus-5 +3"
    assert row["model"] != "claude-opus-5", "team session rendered as a solo one"
    db.close()


def test_rollup_labels_mixed_children():
    db = _make_db()
    _seed(db, "claude-opus-5", ["claude-sonnet-5", "claude-sonnet-5", "claude-opus-5"])
    label = get_today_sessions(db)[0]["model"]
    assert "2x claude-sonnet-5" in label
    assert "claude-opus-5" in label.split("+", 1)[1], "same-model child dropped from label"
    db.close()


def test_orphan_subagent_is_listed_rather_than_dropped():
    """A session spanning midnight must not lose its subagents' cost."""
    db = _make_db()
    db.upsert_session("parent-yesterday", "claude_code", model="claude-opus-5",
                      output_tokens=100, started_at="2020-01-01T10:00:00")
    db.upsert_session("agent-today", "claude_code", model="claude-sonnet-5",
                      output_tokens=42, estimated_cost_usd=0.3,
                      started_at=_today(), parent_session_id="parent-yesterday")
    db.commit()

    rows = get_today_sessions(db)
    assert [r["session_id"] for r in rows] == ["agent-today"]
    assert rows[0]["output_tokens"] == 42
    assert rows[0]["model"] == "claude-sonnet-5"
    db.close()


def test_session_without_subagents_is_unchanged():
    db = _make_db()
    db.upsert_session("solo", "claude_code", model="claude-opus-5",
                      output_tokens=100, estimated_cost_usd=1.0,
                      started_at=_today())
    db.commit()
    row = get_today_sessions(db)[0]
    assert row["model"] == "claude-opus-5"
    assert row["output_tokens"] == 100
    assert "subagent_count" not in row
    db.close()
