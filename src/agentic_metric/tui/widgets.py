"""Custom widgets for the Agentic Metric TUI."""

from __future__ import annotations

from datetime import datetime

from textual.widgets import Static

from ..models import TodayOverview


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
        return dt.strftime("%H:%M")
    except (ValueError, TypeError):
        return ts[:16]


# ── Widgets ───────────────────────────────────────────────────────────


class TodaySummary(Static):
    """3-line top-style summary header showing today's aggregate stats."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._overview: TodayOverview | None = None
        self._active_count: int = 0

    def update_data(self, overview: TodayOverview, active_count: int) -> None:
        self._overview = overview
        self._active_count = active_count
        self.refresh()

    def render(self) -> str:
        ov = self._overview
        if ov is None:
            return "[dim]Loading...[/]"

        n = self._active_count
        active_str = (
            f"[green bold]●[/] [bold]{n}[/] active"
            if n > 0
            else "[dim]○[/] [dim]Idle[/]"
        )

        line1 = (
            f"  Sessions: [bold]{ov.session_count}[/] "
            f"({active_str})    "
            f"Messages: [bold]{ov.message_count}[/]    "
            f"Turns: [bold]{ov.tool_call_count}[/]"
        )

        line2 = (
            f"  Tokens: [bold cyan]{fmt_tokens(ov.total_tokens)}[/] "
            f"(in: {fmt_tokens(ov.input_tokens)}  "
            f"out: {fmt_tokens(ov.output_tokens)}  "
            f"cache_r: {fmt_tokens(ov.cache_read_tokens)}  "
            f"cache_w: {fmt_tokens(ov.cache_creation_tokens)})"
        )

        line3 = f"  Cost: [bold yellow]~{fmt_cost(ov.estimated_cost_usd)}[/]"

        return f"{line1}\n{line2}\n{line3}"
