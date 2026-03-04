"""Typer CLI for agentic-metric."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="agentic-metric",
    help="Monitor token usage and costs across AI coding agents.",
    no_args_is_help=True,
)

console = Console()


@app.command()
def tui() -> None:
    """Launch the interactive TUI dashboard."""
    from .tui.app import AgenticMetricApp

    AgenticMetricApp().run()


@app.command()
def tray(
    foreground: bool = typer.Option(False, "--foreground", "-f", help="Run in foreground (blocking)."),
) -> None:
    """Launch the system tray icon."""
    if foreground:
        from .tray.app import run_tray
        run_tray()
    else:
        import subprocess
        import sys

        subprocess.Popen(
            [sys.executable, "-m", "agentic_metric", "tray", "--foreground"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        console.print("Tray icon launched in background.")


@app.command()
def status() -> None:
    """Show currently active agent sessions."""
    from .collectors import create_default_registry
    from .pricing import estimate_session_cost

    registry = create_default_registry()
    sessions = registry.get_live_sessions()

    if not sessions:
        console.print("No active agents.")
        return

    table = Table(title="Active Agent Sessions")
    table.add_column("PID", justify="right", style="cyan")
    table.add_column("Agent", style="magenta")
    table.add_column("Project", style="green")
    table.add_column("Turns", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Cost", justify="right", style="yellow")
    table.add_column("Model", style="blue")

    for s in sessions:
        cost = estimate_session_cost(s)
        project = s.project_path.split("/")[-1] if s.project_path else ""
        table.add_row(
            str(s.pid),
            s.agent_type,
            project,
            str(s.user_turns),
            f"{s.output_tokens:,}",
            f"${cost:.2f}",
            s.model or "-",
        )

    console.print(table)


@app.command()
def today() -> None:
    """Show today's usage overview."""
    from .store.database import Database
    from .store import aggregator
    from .collectors import create_default_registry
    from .pricing import estimate_session_cost

    db = Database()
    registry = create_default_registry()
    registry.sync_all(db)

    overview = aggregator.get_today_overview(db)

    # Augment with live session data
    live_sessions = registry.get_live_sessions()
    overview.active_agents = len(live_sessions)
    live_cost = sum(estimate_session_cost(s) for s in live_sessions)
    live_out = sum(s.output_tokens for s in live_sessions)
    live_in = sum(s.input_tokens for s in live_sessions)

    db.close()

    console.print(f"\n[bold]Today's Overview[/bold]  ({overview.date})\n")
    console.print(f"  Active:     [bold green]{overview.active_agents} agents[/bold green]")
    console.print(f"  Sessions:   {overview.session_count}")
    console.print(f"  Messages:   {overview.message_count}")
    console.print(f"  Input tok:  {overview.input_tokens:,}")
    console.print(f"  Output tok: {overview.output_tokens:,}")
    console.print(f"  Cache read: {overview.cache_read_tokens:,}")
    console.print(f"  Cache write:{overview.cache_creation_tokens:,}")
    console.print(f"  [bold yellow]Cost:       ${overview.estimated_cost_usd:.2f}[/bold yellow]")
    if live_sessions:
        console.print(f"\n  [dim]Live sessions: {len(live_sessions)} | "
                       f"Output: {live_out:,} | Cost: ${live_cost:.2f}[/dim]\n")

    if overview.by_agent:
        table = Table(title="Per-Agent Breakdown")
        table.add_column("Agent", style="magenta")
        table.add_column("Sessions", justify="right")
        table.add_column("Messages", justify="right")
        table.add_column("Input", justify="right")
        table.add_column("Output", justify="right")
        table.add_column("Cost", justify="right", style="yellow")

        for agent, data in overview.by_agent.items():
            table.add_row(
                agent,
                str(data["session_count"]),
                str(data["message_count"]),
                f"{data['input_tokens']:,}",
                f"{data['output_tokens']:,}",
                f"${data['cost']:.2f}",
            )

        console.print(table)
    else:
        console.print("  No data recorded yet for today.")


@app.command()
def history(
    days: int = typer.Option(30, "--days", "-d", help="Number of days to show."),
) -> None:
    """Show daily usage trends."""
    from .store.database import Database
    from .store import aggregator
    from .collectors import create_default_registry

    db = Database()
    registry = create_default_registry()
    registry.sync_all(db)

    trends = aggregator.get_daily_trends(db, days=days)
    db.close()

    if not trends:
        console.print("No history data available.")
        return

    table = Table(title=f"Daily Trends (last {days} days)")
    table.add_column("Date", style="cyan")
    table.add_column("Sessions", justify="right")
    table.add_column("Messages", justify="right")
    table.add_column("Input", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Cache Read", justify="right")
    table.add_column("Cost", justify="right", style="yellow")

    for t in trends:
        table.add_row(
            t.date,
            str(t.session_count),
            str(t.message_count),
            f"{t.input_tokens:,}",
            f"{t.output_tokens:,}",
            f"{t.cache_read_tokens:,}",
            f"${t.estimated_cost_usd:.2f}",
        )

    console.print(table)


def _fmt_tokens(n: int) -> str:
    """Format token count for compact display: 1234 -> 1.2K, 1234567 -> 1.2M."""
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


@app.command()
def bar() -> None:
    """Print a one-line summary for status bars (i3blocks, waybar, etc.)."""
    import sys
    from .store.database import Database
    from .store import aggregator

    try:
        db = Database()
        overview = aggregator.get_today_overview(db)
        db.close()
    except Exception:
        print("AM: --")
        sys.exit(0)

    all_tokens = (overview.input_tokens + overview.output_tokens
                   + overview.cache_read_tokens + overview.cache_creation_tokens)
    tokens = _fmt_tokens(all_tokens)
    cost = f"${overview.estimated_cost_usd:.2f}"
    # full_text
    print(f"AM: {cost} | {tokens}")
    # short_text
    print(f"AM: {cost}")


@app.command()
def sync() -> None:
    """Force sync all collectors to the database."""
    from .store.database import Database
    from .collectors import create_default_registry

    db = Database()
    registry = create_default_registry()

    console.print("Syncing all collectors...")
    registry.sync_all(db)
    db.close()

    console.print("[green]Sync complete.[/green]")
    console.print(f"  Collectors: {len(registry.get_all())}")
    for c in registry.get_all():
        console.print(f"    - {c.agent_type}")
