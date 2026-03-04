"""Custom widgets for the Agentic Metric TUI."""

from __future__ import annotations

from datetime import datetime

from textual.reactive import reactive
from textual.widgets import Static

from ..models import LiveSession
from ..pricing import estimate_session_cost


# ── Formatting helpers ────────────────────────────────────────────────


def fmt_tokens(n: int) -> str:
    """Format a token count for compact display."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def fmt_cost(usd: float) -> str:
    """Format a USD cost value."""
    if usd >= 1.0:
        return f"${usd:.2f}"
    return f"${usd:.3f}"


def ts_to_local(ts: str) -> str:
    """Convert an ISO-8601 timestamp to a short local-time string."""
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%m-%d %H:%M")
    except (ValueError, TypeError):
        return ts[:16]


# ── Widgets ───────────────────────────────────────────────────────────


class StatusBar(Static):
    """Top-level status indicator showing how many agents are active."""

    active_count: reactive[int] = reactive(0)

    def render(self) -> str:
        n = self.active_count
        if n > 0:
            agents = "agent" if n == 1 else "agents"
            return f"[green bold]\u25cf[/] [bold]{n}[/] {agents} active"
        return "[dim]\u25cb[/] [dim]Idle[/]"


class LiveSummary(Static):
    """Aggregate summary bar for all running sessions."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._sessions: list[LiveSession] = []

    def set_sessions(self, sessions: list[LiveSession]) -> None:
        self._sessions = sessions
        self.refresh()

    def render(self) -> str:
        ss = self._sessions
        if not ss:
            return "[bold]Running Sessions[/]  [dim]None[/]"

        total_turns = sum(s.user_turns for s in ss)
        total_out = sum(s.output_tokens for s in ss)
        total_cost = sum(estimate_session_cost(s) for s in ss)

        return (
            f"[bold]Running[/] [bold green]{len(ss)}[/]  "
            f"Turns [bold cyan]{total_turns}[/]  "
            f"Output [bold cyan]{fmt_tokens(total_out)}[/]  "
            f"Est. Cost [bold yellow]{fmt_cost(total_cost)}[/]"
        )
