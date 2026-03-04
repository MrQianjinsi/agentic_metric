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
from ..store.aggregator import get_daily_trends
from ..store.database import Database
from .widgets import LiveSummary, StatusBar, fmt_cost, fmt_tokens, ts_to_local


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

    # ── Layout ────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent("Dashboard", "History"):
            with TabPane("Dashboard", id="tab-dashboard"):
                yield StatusBar(id="status-bar")
                yield LiveSummary(id="live-summary")
                yield DataTable(id="live-table")
                yield PlotextPlot(id="today-chart")
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
        self.query_one("#status-bar", StatusBar).active_count = len(self._live_sessions)
        self.query_one("#live-summary", LiveSummary).set_sessions(self._live_sessions)
        self._populate_live_table()
        self._draw_today_chart()

    def _populate_live_table(self) -> None:
        table = self.query_one("#live-table", DataTable)
        table.clear(columns=True)
        table.add_columns(
            "PID", "Project", "Branch", "Turns",
            "Output", "Cache Read", "Cache Write",
            "Cost", "Model", "Prompt",
        )
        for s in self._live_sessions:
            cost = estimate_session_cost(s)
            model_short = s.model.split("-20")[0] if s.model else ""
            project_short = s.project_path.split("/")[-1] if s.project_path else ""
            branch = s.git_branch or ""
            prompt = (s.first_prompt[:28] + "\u2026") if len(s.first_prompt) > 28 else s.first_prompt

            table.add_row(
                str(s.pid) if s.pid else "",
                project_short,
                branch,
                str(s.user_turns),
                fmt_tokens(s.output_tokens),
                fmt_tokens(s.cache_read_tokens),
                fmt_tokens(s.cache_creation_tokens),
                fmt_cost(cost),
                model_short,
                prompt,
            )

    def _draw_today_chart(self) -> None:
        """Stacked bar chart of today's tokens by session."""
        plot_widget = self.query_one("#today-chart", PlotextPlot)
        plt = plot_widget.plt
        plt.clear_figure()
        plt.title("Today's Token Consumption (Running Sessions)")

        if not self._live_sessions:
            plt.title("Today's Token Consumption \u2014 no active sessions")
            plot_widget.refresh()
            return

        names: list[str] = []
        output_vals: list[float] = []
        cache_r_vals: list[float] = []
        cache_w_vals: list[float] = []

        for s in self._live_sessions:
            proj = s.project_path.split("/")[-1] if s.project_path else s.session_id[:8]
            label = f"{proj}" if not s.pid else f"{proj}:{s.pid}"
            names.append(label)
            output_vals.append(s.output_tokens / 1000)
            cache_r_vals.append(s.cache_read_tokens / 1000)
            cache_w_vals.append(s.cache_creation_tokens / 1000)

        xs = list(range(len(names)))
        plt.stacked_bar(
            xs,
            [output_vals, cache_w_vals, cache_r_vals],
            labels=["Output", "Cache Write", "Cache Read"],
        )
        plt.xticks(xs, names)
        plt.ylabel("K tokens")
        plot_widget.refresh()

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
            plt.title("Daily Trend \u2014 no data")
            plot_widget.refresh()
            return

        dates = [t.date[5:] for t in trends]  # MM-DD
        token_vals = [t.total_tokens / 1000 for t in trends]
        cost_vals = [t.estimated_cost_usd for t in trends]
        xs = list(range(len(dates)))

        plt.plot(xs, token_vals, label="Tokens (K)", marker="braille")
        plt.plot(xs, cost_vals, label="Cost ($)", marker="braille")
        plt.xticks(xs, dates)
        plt.xlabel("Date")
        plt.ylabel("Value")
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
        self.query_one("#status-bar", StatusBar).active_count = len(sessions)
        self.query_one("#live-summary", LiveSummary).set_sessions(sessions)
        self._populate_live_table()
        self._draw_today_chart()

    # ── Auto sync (5 min interval) ────────────────────────────────────

    def _auto_sync(self) -> None:
        self.run_worker(self._sync_worker, thread=True)

    async def _sync_worker(self) -> None:
        self._collectors.sync_all(self._db)
        self._db.commit()
        self.call_from_thread(self._refresh_history)

    def _refresh_history(self) -> None:
        self._draw_trend_chart()
        daily_table = self.query_one("#daily-table", DataTable)
        daily_table.clear(columns=True)
        self._populate_daily_table()

    # ── Actions ───────────────────────────────────────────────────────

    def action_refresh_data(self) -> None:
        self._collectors.sync_all(self._db)
        self._db.commit()
        self._populate_dashboard()
        self._refresh_history()
        self.notify("Data refreshed")

    def on_unmount(self) -> None:
        self._db.close()
