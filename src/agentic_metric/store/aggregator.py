"""Query layer: today overview, daily trends, model breakdown."""

from __future__ import annotations

from datetime import datetime, timedelta

from ..models import DailyTrend, TodayOverview
from .database import Database


def get_today_overview(db: Database) -> TodayOverview:
    """Get aggregated stats for today across all agents."""
    today = datetime.now().strftime("%Y-%m-%d")
    rows = db.conn.execute(
        """SELECT agent_type,
                  SUM(session_count) AS session_count,
                  SUM(message_count) AS message_count,
                  SUM(tool_call_count) AS tool_call_count,
                  SUM(input_tokens) AS input_tokens,
                  SUM(output_tokens) AS output_tokens,
                  SUM(cache_read_tokens) AS cache_read_tokens,
                  SUM(cache_creation_tokens) AS cache_creation_tokens,
                  SUM(estimated_cost_usd) AS estimated_cost_usd
           FROM daily_stats
           WHERE date = ?
           GROUP BY agent_type
        """,
        (today,),
    ).fetchall()

    overview = TodayOverview(date=today)
    for row in rows:
        r = dict(row)
        at = r["agent_type"]
        overview.session_count += r["session_count"] or 0
        overview.message_count += r["message_count"] or 0
        overview.tool_call_count += r["tool_call_count"] or 0
        overview.input_tokens += r["input_tokens"] or 0
        overview.output_tokens += r["output_tokens"] or 0
        overview.cache_read_tokens += r["cache_read_tokens"] or 0
        overview.cache_creation_tokens += r["cache_creation_tokens"] or 0
        overview.estimated_cost_usd += r["estimated_cost_usd"] or 0
        overview.by_agent[at] = {
            "session_count": r["session_count"] or 0,
            "message_count": r["message_count"] or 0,
            "input_tokens": r["input_tokens"] or 0,
            "output_tokens": r["output_tokens"] or 0,
            "cost": r["estimated_cost_usd"] or 0,
        }
    return overview


def get_daily_trends(db: Database, days: int = 30) -> list[DailyTrend]:
    """Get daily aggregated stats for the last N days."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = db.conn.execute(
        """SELECT date,
                  SUM(session_count) AS session_count,
                  SUM(message_count) AS message_count,
                  SUM(input_tokens) AS input_tokens,
                  SUM(output_tokens) AS output_tokens,
                  SUM(cache_read_tokens) AS cache_read_tokens,
                  SUM(cache_creation_tokens) AS cache_creation_tokens,
                  SUM(estimated_cost_usd) AS estimated_cost_usd
           FROM daily_stats
           WHERE date >= ?
           GROUP BY date
           ORDER BY date
        """,
        (cutoff,),
    ).fetchall()

    return [
        DailyTrend(
            date=r["date"],
            session_count=r["session_count"] or 0,
            message_count=r["message_count"] or 0,
            input_tokens=r["input_tokens"] or 0,
            output_tokens=r["output_tokens"] or 0,
            cache_read_tokens=r["cache_read_tokens"] or 0,
            cache_creation_tokens=r["cache_creation_tokens"] or 0,
            estimated_cost_usd=r["estimated_cost_usd"] or 0,
        )
        for r in rows
    ]


def get_model_breakdown(db: Database, days: int = 30) -> list[dict]:
    """Get token/cost breakdown by model for the last N days."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = db.conn.execute(
        """SELECT model,
                  SUM(input_tokens) AS input_tokens,
                  SUM(output_tokens) AS output_tokens,
                  SUM(cache_read_tokens) AS cache_read_tokens,
                  SUM(cache_creation_tokens) AS cache_creation_tokens,
                  SUM(estimated_cost_usd) AS estimated_cost_usd
           FROM model_daily_usage
           WHERE date >= ?
           GROUP BY model
           ORDER BY estimated_cost_usd DESC
        """,
        (cutoff,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_top_projects(db: Database, limit: int = 10) -> list[dict]:
    """Get top projects by message count."""
    rows = db.conn.execute(
        """SELECT project_path,
                  COUNT(*) AS session_count,
                  SUM(message_count) AS total_messages,
                  SUM(estimated_cost_usd) AS total_cost
           FROM sessions
           WHERE project_path != ''
           GROUP BY project_path
           ORDER BY total_messages DESC
           LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
