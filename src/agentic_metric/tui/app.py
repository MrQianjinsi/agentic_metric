"""Textual TUI application for Agentic Metric."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header, TabbedContent, TabPane
from textual_plotext import PlotextPlot

from ..collectors import CollectorRegistry, create_default_registry
from ..config import DATA_SYNC_INTERVAL, LIVE_REFRESH_INTERVAL
from ..models import LiveSession
from ..pricing import estimate_session_cost
from ..store.aggregator import get_daily_trends, get_today_overview, get_today_sessions
from ..store.database import Database
from .widgets import TodaySummary, fmt_cost, fmt_tokens, ts_to_local


class AgenticMetricApp(App):
    """Multi-agent coding metric monitor."""

    TITLE = "Agentic Metric"
    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = "styles.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh_data", "Refresh"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._db = Database()
        self._collectors: CollectorRegistry = create_default_registry()
        self._collectors.sync_all(self._db)
        self._db.commit()
        self._live_sessions: list[LiveSession] = []
        self._today_sessions: list[dict] = []

    # ── Layout ────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent("Today", "History"):
            with TabPane("Today", id="tab-dashboard"):
                yield TodaySummary(id="today-summary")
                yield DataTable(id="live-table")
            with TabPane("History", id="tab-history"):
                yield PlotextPlot(id="trend-chart")
                yield DataTable(id="daily-table")
        yield Footer()

    def on_mount(self) -> None:
        self._populate_dashboard()
        self._populate_history()
        self.set_interval(LIVE_REFRESH_INTERVAL, self._tick_live)
        self.set_interval(DATA_SYNC_INTERVAL, self._auto_sync)

    # ── Dashboard ─────────────────────────────────────────────────────

    def _populate_dashboard(self) -> None:
        self._live_sessions = self._collectors.get_live_sessions()
        self._today_sessions = get_today_sessions(self._db)
        overview = get_today_overview(self._db)
        self.query_one("#today-summary", TodaySummary).update_data(
            overview, len(self._live_sessions)
        )
        self._populate_session_table()

    def _get_live_pids(self) -> set[int]:
        return {s.pid for s in self._live_sessions if s.pid}

    def _get_live_session_ids(self) -> set[str]:
        return {s.session_id for s in self._live_sessions}

    def _populate_session_table(self) -> None:
        table = self.query_one("#live-table", DataTable)
        table.clear(columns=True)
        table.add_columns(
            "Status", "Project", "Branch", "Turns",
            "Output", "Cache R", "Cost",
            "Model", "Started", "Prompt",
        )

        live_ids = self._get_live_session_ids()
        db_ids = {s["session_id"] for s in self._today_sessions}

        # Build rows: active first, then finished (by started_at desc)
        active_rows: list[tuple] = []
        finished_rows: list[tuple] = []

        for s in self._today_sessions:
            sid = s["session_id"]
            is_active = sid in live_ids
            status = "[green]●[/]" if is_active else "[dim]○[/]"
            project = (s["project_path"] or "").rsplit("/", 1)[-1]
            branch = s["git_branch"] or ""
            turns = str(s["user_turns"] or 0)
            output = fmt_tokens(s["output_tokens"] or 0)
            cache_r = fmt_tokens(s["cache_read_tokens"] or 0)
            cost = fmt_cost(s["estimated_cost_usd"] or 0)
            model = (s["model"] or "").split("-20")[0]
            started = ts_to_local(s["started_at"] or "")
            prompt_raw = s["first_prompt"] or ""
            prompt = (prompt_raw[:40] + "…") if len(prompt_raw) > 40 else prompt_raw

            row = (status, project, branch, turns, output, cache_r, cost, model, started, prompt)
            if is_active:
                active_rows.append(row)
            else:
                finished_rows.append(row)

        # Merge live sessions not yet in DB (just started, not synced)
        for ls in self._live_sessions:
            if ls.session_id in db_ids:
                continue
            cost = estimate_session_cost(ls)
            project = ls.project_path.rsplit("/", 1)[-1] if ls.project_path else ""
            prompt_raw = ls.first_prompt or ""
            prompt = (prompt_raw[:40] + "…") if len(prompt_raw) > 40 else prompt_raw
            active_rows.append((
                "[green]●[/]",
                project,
                ls.git_branch or "",
                str(ls.user_turns),
                fmt_tokens(ls.output_tokens),
                fmt_tokens(ls.cache_read_tokens),
                fmt_cost(cost),
                (ls.model or "").split("-20")[0],
                ts_to_local(ls.started),
                prompt,
            ))

        for row in active_rows:
            table.add_row(*row)
        for row in finished_rows:
            table.add_row(*row)

    # ── History ───────────────────────────────────────────────────────

    def _populate_history(self) -> None:
        self._draw_trend_chart()
        self._populate_daily_table()

    def _draw_trend_chart(self) -> None:
        """Line chart of daily tokens and cost over the last 30 days."""
        trends = get_daily_trends(self._db, days=30)
        plot_widget = self.query_one("#trend-chart", PlotextPlot)
        plt = plot_widget.plt
        plt.clear_figure()
        plt.title("Daily Tokens & Cost (30 days)")

        if not trends:
            plt.title("Daily Trend — no data")
            plot_widget.refresh()
            return

        dates = [t.date[5:] for t in trends]  # MM-DD
        raw_tokens = [t.total_tokens for t in trends]
        cost_vals = [t.estimated_cost_usd for t in trends]
        xs = list(range(len(dates)))

        max_tok = max(raw_tokens) if raw_tokens else 0
        if max_tok >= 1_000_000_000:
            divisor, unit = 1_000_000_000, "B"
        elif max_tok >= 1_000_000:
            divisor, unit = 1_000_000, "M"
        elif max_tok >= 1_000:
            divisor, unit = 1_000, "K"
        else:
            divisor, unit = 1, ""

        token_vals = [t / divisor for t in raw_tokens]

        plt.plot(xs, token_vals, label=f"Tokens ({unit})", marker="braille")
        plt.plot(xs, cost_vals, label="Cost ($)", marker="braille")
        plt.xticks(xs, dates)
        plt.xlabel("Date")
        plot_widget.refresh()

    def _populate_daily_table(self) -> None:
        trends = get_daily_trends(self._db, days=30)
        table = self.query_one("#daily-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Date", "Sessions", "Messages", "Tokens", "Cost", "Agent")

        for t in reversed(trends):
            agent = t.agent_type if t.agent_type else "all"
            table.add_row(
                t.date,
                str(t.session_count),
                str(t.message_count),
                fmt_tokens(t.total_tokens),
                fmt_cost(t.estimated_cost_usd),
                agent,
            )

    # ── Live refresh (1s interval) ────────────────────────────────────

    def _tick_live(self) -> None:
        self.run_worker(self._live_worker, thread=True, exclusive=True, group="live")

    async def _live_worker(self) -> None:
        sessions = self._collectors.get_live_sessions()
        self.call_from_thread(self._update_live, sessions)

    def _update_live(self, sessions: list[LiveSession]) -> None:
        self._live_sessions = sessions
        overview = get_today_overview(self._db)
        self.query_one("#today-summary", TodaySummary).update_data(
            overview, len(sessions)
        )
        self._populate_session_table()

    # ── Auto sync (5 min interval) ────────────────────────────────────

    def _auto_sync(self) -> None:
        self.run_worker(self._sync_worker, thread=True)

    async def _sync_worker(self) -> None:
        self._collectors.sync_all(self._db)
        self._db.commit()
        self.call_from_thread(self._refresh_all)

    def _refresh_all(self) -> None:
        self._today_sessions = get_today_sessions(self._db)
        self._populate_dashboard()
        self._draw_trend_chart()
        daily_table = self.query_one("#daily-table", DataTable)
        daily_table.clear(columns=True)
        self._populate_daily_table()

    # ── Actions ───────────────────────────────────────────────────────

    def action_refresh_data(self) -> None:
        self._collectors.sync_all(self._db)
        self._db.commit()
        self._populate_dashboard()
        self._draw_trend_chart()
        daily_table = self.query_one("#daily-table", DataTable)
        daily_table.clear(columns=True)
        self._populate_daily_table()
        self.notify("Data refreshed")

    def on_unmount(self) -> None:
        self._db.close()
