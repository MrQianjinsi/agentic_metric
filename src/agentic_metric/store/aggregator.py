"""Query layer: today overview, daily trends, model breakdown."""

from __future__ import annotations

from datetime import datetime, timedelta

from ..models import DailyTrend, LiveSession, TodayOverview
from ..pricing import estimate_cost, estimate_session_cost
from .database import Database


def get_today_overview(db: Database) -> TodayOverview:
    """Get aggregated stats for today across all agents."""
    today = datetime.now().strftime("%Y-%m-%d")
    rows = db.conn.execute(
        """SELECT agent_type,
                  COUNT(*) AS session_count,
                  SUM(message_count) AS message_count,
                  SUM(user_turns) AS user_turns,
                  SUM(input_tokens) AS input_tokens,
                  SUM(output_tokens) AS output_tokens,
                  SUM(cache_read_tokens) AS cache_read_tokens,
                  SUM(cache_creation_tokens) AS cache_creation_tokens,
                  SUM(estimated_cost_usd) AS estimated_cost_usd
           FROM sessions
           WHERE date(started_at) = ?
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
        overview.tool_call_count += r["user_turns"] or 0
        overview.input_tokens += r["input_tokens"] or 0
        overview.output_tokens += r["output_tokens"] or 0
        overview.cache_read_tokens += r["cache_read_tokens"] or 0
        overview.cache_creation_tokens += r["cache_creation_tokens"] or 0
        overview.estimated_cost_usd += r["estimated_cost_usd"] or 0
        overview.by_agent[at] = {
            "session_count": r["session_count"] or 0,
            "turns": r["user_turns"] or 0,
            "message_count": r["message_count"] or 0,
            "input_tokens": r["input_tokens"] or 0,
            "output_tokens": r["output_tokens"] or 0,
            "cost": r["estimated_cost_usd"] or 0,
        }
    return overview


def merge_live_into_overview(
    overview: TodayOverview,
    live_sessions: list[LiveSession],
    today_sessions: list[dict],
) -> None:
    """Merge live session data into overview so totals include active sessions.

    Handles two cases:
    - Sessions in DB today: add delta if live data is fresher.
    - Live sessions not in today's DB rows (e.g. started yesterday but still
      running): add full live values.
    """
    db_ids = {s["session_id"] for s in today_sessions}
    db_by_id = {s["session_id"]: s for s in today_sessions}

    for ls in live_sessions:
        cost = estimate_session_cost(ls)
        at = ls.agent_type or ""

        if ls.session_id in db_ids:
            db_s = db_by_id[ls.session_id]
            if ls.output_tokens > 0:
                d_msg = max(0, ls.message_count - (db_s["message_count"] or 0))
                d_turns = max(0, ls.user_turns - (db_s["user_turns"] or 0))
                d_in = max(0, ls.input_tokens - (db_s["input_tokens"] or 0))
                d_out = max(0, ls.output_tokens - (db_s["output_tokens"] or 0))
                d_cr = max(0, ls.cache_read_tokens - (db_s["cache_read_tokens"] or 0))
                d_cw = max(0, ls.cache_creation_tokens - (db_s["cache_creation_tokens"] or 0))
                d_cost = max(0, cost - (db_s["estimated_cost_usd"] or 0))

                overview.message_count += d_msg
                overview.tool_call_count += d_turns
                overview.input_tokens += d_in
                overview.output_tokens += d_out
                overview.cache_read_tokens += d_cr
                overview.cache_creation_tokens += d_cw
                overview.estimated_cost_usd += d_cost

                if at in overview.by_agent:
                    ba = overview.by_agent[at]
                    ba["turns"] = ba.get("turns", 0) + d_turns
                    ba["message_count"] = ba.get("message_count", 0) + d_msg
                    ba["input_tokens"] = ba.get("input_tokens", 0) + d_in
                    ba["output_tokens"] = ba.get("output_tokens", 0) + d_out
                    ba["cost"] = ba.get("cost", 0) + d_cost
        else:
            # Use today-only values for cross-day sessions
            t_turns = ls.today_user_turns if ls.today_user_turns >= 0 else ls.user_turns
            t_msgs = ls.today_message_count if ls.today_message_count >= 0 else ls.message_count
            t_in = ls.today_input_tokens if ls.today_input_tokens >= 0 else ls.input_tokens
            t_out = ls.today_output_tokens if ls.today_output_tokens >= 0 else ls.output_tokens
            t_cr = ls.today_cache_read_tokens if ls.today_cache_read_tokens >= 0 else ls.cache_read_tokens
            t_cw = ls.today_cache_creation_tokens if ls.today_cache_creation_tokens >= 0 else ls.cache_creation_tokens
            t_cost = estimate_cost(ls.model, t_in, t_out, t_cr, t_cw)

            if ls.user_turns == 0 and ls.output_tokens == 0:
                continue
            overview.session_count += 1
            overview.message_count += t_msgs
            overview.tool_call_count += t_turns
            overview.input_tokens += t_in
            overview.output_tokens += t_out
            overview.cache_read_tokens += t_cr
            overview.cache_creation_tokens += t_cw
            overview.estimated_cost_usd += t_cost

            ba = overview.by_agent.get(at)
            if ba:
                ba["session_count"] = ba.get("session_count", 0) + 1
                ba["turns"] = ba.get("turns", 0) + t_turns
                ba["message_count"] = ba.get("message_count", 0) + t_msgs
                ba["input_tokens"] = ba.get("input_tokens", 0) + t_in
                ba["output_tokens"] = ba.get("output_tokens", 0) + t_out
                ba["cost"] = ba.get("cost", 0) + t_cost
            else:
                overview.by_agent[at] = {
                    "session_count": 1,
                    "turns": t_turns,
                    "message_count": t_msgs,
                    "input_tokens": t_in,
                    "output_tokens": t_out,
                    "cost": t_cost,
                }


def merge_live_into_trends(
    trends: list[DailyTrend],
    live_sessions: list[LiveSession],
    today_sessions: list[dict],
) -> None:
    """Merge live session data into daily trends for today's entry.

    Same logic as merge_live_into_overview but operates on the trend list.
    """
    today = datetime.now().strftime("%Y-%m-%d")

    # Find or create today's entry (trends are ordered DESC)
    today_trend = None
    for t in trends:
        if t.date == today:
            today_trend = t
            break
    if today_trend is None:
        today_trend = DailyTrend(date=today)
        trends.insert(0, today_trend)

    db_ids = {s["session_id"] for s in today_sessions}
    db_by_id = {s["session_id"]: s for s in today_sessions}

    for ls in live_sessions:
        if ls.session_id in db_ids:
            db_s = db_by_id[ls.session_id]
            if ls.output_tokens > 0:
                today_trend.user_turns += max(0, ls.user_turns - (db_s["user_turns"] or 0))
                today_trend.message_count += max(0, ls.message_count - (db_s["message_count"] or 0))
                today_trend.input_tokens += max(0, ls.input_tokens - (db_s["input_tokens"] or 0))
                today_trend.output_tokens += max(0, ls.output_tokens - (db_s["output_tokens"] or 0))
                today_trend.cache_read_tokens += max(0, ls.cache_read_tokens - (db_s["cache_read_tokens"] or 0))
                today_trend.cache_creation_tokens += max(0, ls.cache_creation_tokens - (db_s["cache_creation_tokens"] or 0))
                d_cost = max(0, estimate_session_cost(ls) - (db_s["estimated_cost_usd"] or 0))
                today_trend.estimated_cost_usd += d_cost
        else:
            if ls.user_turns == 0 and ls.output_tokens == 0:
                continue
            t_turns = ls.today_user_turns if ls.today_user_turns >= 0 else ls.user_turns
            t_msgs = ls.today_message_count if ls.today_message_count >= 0 else ls.message_count
            t_in = ls.today_input_tokens if ls.today_input_tokens >= 0 else ls.input_tokens
            t_out = ls.today_output_tokens if ls.today_output_tokens >= 0 else ls.output_tokens
            t_cr = ls.today_cache_read_tokens if ls.today_cache_read_tokens >= 0 else ls.cache_read_tokens
            t_cw = ls.today_cache_creation_tokens if ls.today_cache_creation_tokens >= 0 else ls.cache_creation_tokens
            t_cost = estimate_cost(ls.model, t_in, t_out, t_cr, t_cw)

            today_trend.session_count += 1
            today_trend.user_turns += t_turns
            today_trend.message_count += t_msgs
            today_trend.input_tokens += t_in
            today_trend.output_tokens += t_out
            today_trend.cache_read_tokens += t_cr
            today_trend.cache_creation_tokens += t_cw
            today_trend.estimated_cost_usd += t_cost


def get_daily_trends(db: Database, days: int = 30) -> list[DailyTrend]:
    """Get daily aggregated stats for the last N days."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = db.conn.execute(
        """SELECT substr(started_at, 1, 10) AS date,
                  COUNT(*) AS session_count,
                  SUM(user_turns) AS user_turns,
                  SUM(message_count) AS message_count,
                  SUM(input_tokens) AS input_tokens,
                  SUM(output_tokens) AS output_tokens,
                  SUM(cache_read_tokens) AS cache_read_tokens,
                  SUM(cache_creation_tokens) AS cache_creation_tokens,
                  SUM(estimated_cost_usd) AS estimated_cost_usd
           FROM sessions
           WHERE substr(started_at, 1, 10) >= ?
           GROUP BY substr(started_at, 1, 10)
           ORDER BY date DESC
        """,
        (cutoff,),
    ).fetchall()

    return [
        DailyTrend(
            date=r["date"],
            session_count=r["session_count"] or 0,
            user_turns=r["user_turns"] or 0,
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
           FROM sessions
           WHERE substr(started_at, 1, 10) >= ? AND model != ''
           GROUP BY model
           ORDER BY estimated_cost_usd DESC
        """,
        (cutoff,),
    ).fetchall()
    return [dict(r) for r in rows]


def _short_model(model: str) -> str:
    """Drop a trailing date stamp so models fit a table cell."""
    return (model or "").split("-20")[0]


def get_today_sessions(db: Database) -> list[dict]:
    """Get all sessions from today, ordered by started_at descending.

    Subagent rows are folded into the session that dispatched them rather than
    listed separately: a session with five subagents would otherwise push five
    extra rows into the table. The parent row's tokens and cost therefore cover
    the whole session tree, and `model` names every model that ran in it
    (e.g. "opus-5 +5x sonnet-5"). Subagents whose parent is not itself in
    today's rows are kept as their own rows so their cost is never dropped.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    rows = db.conn.execute(
        """SELECT session_id, agent_type, project_path, git_branch, model,
                  message_count, user_turns, input_tokens, output_tokens,
                  cache_read_tokens, cache_creation_tokens, estimated_cost_usd,
                  started_at, ended_at, first_prompt, last_prompt,
                  parent_session_id
           FROM sessions
           WHERE date(started_at) = ?
           ORDER BY started_at DESC
        """,
        (today,),
    ).fetchall()
    sessions = [dict(r) for r in rows]

    by_id = {s["session_id"]: s for s in sessions}
    children: dict[str, list[dict]] = {}
    for s in sessions:
        parent = s.get("parent_session_id") or ""
        if parent and parent in by_id:
            children.setdefault(parent, []).append(s)

    folded: list[dict] = []
    for s in sessions:
        parent = s.get("parent_session_id") or ""
        if parent and parent in by_id:
            continue  # folded into its parent below
        kids = children.get(s["session_id"])
        if kids:
            for key in ("message_count", "user_turns", "input_tokens",
                        "output_tokens", "cache_read_tokens",
                        "cache_creation_tokens"):
                s[key] = (s[key] or 0) + sum(k[key] or 0 for k in kids)
            s["estimated_cost_usd"] = (s["estimated_cost_usd"] or 0) + sum(
                k["estimated_cost_usd"] or 0 for k in kids
            )
            counts: dict[str, int] = {}
            for k in kids:
                m = _short_model(k["model"])
                if m:
                    counts[m] = counts.get(m, 0) + 1
            own = _short_model(s["model"])
            # Never drop a subagent from the label. A subagent running the SAME
            # model as its parent still costs money and still means the session
            # was a team -- filtering it out would render such a session
            # indistinguishable from a solo one.
            if counts and set(counts) == {own}:
                # every subagent used the parent's model: "opus-5 +3"
                s["model"] = f"{own} +{counts[own]}"
            elif counts:
                parts = [
                    m if n == 1 else f"{n}x {m}"
                    for m, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
                ]
                s["model"] = f"{own} +" + " +".join(parts)
            s["subagent_count"] = len(kids)
        folded.append(s)
    return folded


def get_model_breakdown(db: Database, date: str | None = None) -> list[dict]:
    """Per-model totals for one day, biggest cost first.

    Counts every row, subagents included -- the point of this view is to answer
    "where did the money go" for a session tree that used several models, which
    the per-session label can only hint at.
    """
    day = date or datetime.now().strftime("%Y-%m-%d")
    rows = db.conn.execute(
        """SELECT model,
                  COUNT(*) AS session_count,
                  SUM(input_tokens) AS input_tokens,
                  SUM(output_tokens) AS output_tokens,
                  SUM(cache_read_tokens) AS cache_read_tokens,
                  SUM(cache_creation_tokens) AS cache_creation_tokens,
                  SUM(estimated_cost_usd) AS cost,
                  SUM(CASE WHEN parent_session_id != '' THEN 1 ELSE 0 END)
                      AS subagent_count
           FROM sessions
           WHERE date(started_at) = ? AND model != ''
           GROUP BY model
           ORDER BY cost DESC
        """,
        (day,),
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
