"""Typer CLI for agentic-metric."""

from __future__ import annotations

from importlib.metadata import version as _pkg_version

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="agentic-metric",
    help="Monitor token usage and costs across AI coding agents.",
    invoke_without_command=True,
    add_completion=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
pricing_app = typer.Typer(
    help="View and manage model pricing.",
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
app.add_typer(pricing_app, name="pricing")


@pricing_app.callback(invoke_without_command=True)
def _pricing_default(ctx: typer.Context) -> None:
    """Show help by default."""
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()

console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"agentic-metric {_pkg_version('agentic-metric')}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def _default(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", "-v", callback=_version_callback,
        is_eager=True, help="Show version and exit.",
    ),
) -> None:
    """Launch TUI by default when no command is given."""
    if ctx.invoked_subcommand is None:
        tui()


@app.command()
def tui() -> None:
    """Launch the interactive TUI dashboard."""
    from .tui.app import AgenticMetricApp

    AgenticMetricApp().run()


@app.command()
def status() -> None:
    """Show currently active agent sessions."""
    from .collectors import create_default_registry
    from .pricing import estimate_session_cost

    registry = create_default_registry()
    sessions = [s for s in registry.get_live_sessions()
                if s.user_turns > 0 or s.output_tokens > 0]

    if not sessions:
        console.print("No active agents.")
        return

    table = Table(title="Active Agent Sessions")
    table.add_column("PID", justify="right", style="cyan")
    table.add_column("Agent", style="magenta")
    table.add_column("Project", style="green")
    table.add_column("Model", style="blue")
    table.add_column("Turns", justify="right")
    table.add_column("Messages", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost", justify="right", style="yellow")

    for s in sessions:
        cost = estimate_session_cost(s)
        project = s.project_path.split("/")[-1] if s.project_path else ""
        table.add_row(
            str(s.pid),
            s.agent_type,
            project,
            s.model or "-",
            str(s.user_turns),
            str(s.message_count),
            _fmt_tokens(s.total_tokens),
            f"${cost:.2f}",
        )

    console.print(table)


@app.command()
def today() -> None:
    """Show today's usage overview."""
    from .store.database import Database
    from .store import aggregator
    from .collectors import create_default_registry

    db = Database()
    registry = create_default_registry()
    registry.sync_all(db)

    overview = aggregator.get_today_overview(db)
    today_sessions = aggregator.get_today_sessions(db)
    by_model = aggregator.get_model_breakdown(db)
    live_sessions = registry.get_live_sessions()
    aggregator.merge_live_into_overview(overview, live_sessions, today_sessions)
    overview.active_agents = sum(
        1 for s in live_sessions if s.user_turns > 0 or s.output_tokens > 0
    )

    db.close()

    table = Table(title=f"Today's Overview  ({overview.date})")
    table.add_column("Agent", style="magenta")
    table.add_column("Sessions", justify="right")
    table.add_column("Turns", justify="right")
    table.add_column("Messages", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost", justify="right", style="yellow")

    if overview.by_agent:
        for agent, data in overview.by_agent.items():
            total_tokens = data["input_tokens"] + data["output_tokens"]
            table.add_row(
                agent,
                str(data["session_count"]),
                str(data["turns"]),
                str(data["message_count"]),
                _fmt_tokens(total_tokens),
                f"${data['cost']:.2f}",
            )
        table.add_section()

    active_str = f" ([green]{overview.active_agents} active[/green])" if overview.active_agents else ""
    table.add_row(
        "[bold]Total[/bold]",
        f"[bold]{overview.session_count}[/bold]{active_str}",
        f"[bold]{overview.tool_call_count}[/bold]",
        f"[bold]{overview.message_count}[/bold]",
        f"[bold]{_fmt_tokens(overview.total_tokens)}[/bold]",
        f"[bold yellow]${overview.estimated_cost_usd:.2f}[/bold yellow]",
    )

    console.print(table)

    if by_model:
        mt = Table(title="By model")
        mt.add_column("Model", style="cyan")
        mt.add_column("Sessions", justify="right")
        mt.add_column("of which sub", justify="right", style="dim")
        mt.add_column("Tokens", justify="right")
        mt.add_column("Cost", justify="right", style="yellow")
        for m in by_model:
            total_tokens = (
                (m["input_tokens"] or 0)
                + (m["output_tokens"] or 0)
                + (m["cache_read_tokens"] or 0)
                + (m["cache_creation_tokens"] or 0)
            )
            mt.add_row(
                m["model"],
                str(m["session_count"]),
                str(m["subagent_count"]) if m["subagent_count"] else "-",
                _fmt_tokens(total_tokens),
                f"${m['cost'] or 0:.2f}",
            )
        console.print(mt)


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
    today_sessions = aggregator.get_today_sessions(db)
    live_sessions = registry.get_live_sessions()
    aggregator.merge_live_into_trends(trends, live_sessions, today_sessions)
    db.close()

    if not trends:
        console.print("No history data available.")
        return

    table = Table(title=f"Daily Trends (last {days} days)")
    table.add_column("Date", style="cyan")
    table.add_column("Sessions", justify="right")
    table.add_column("Turns", justify="right")
    table.add_column("Messages", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost", justify="right", style="yellow")

    for t in trends:
        table.add_row(
            t.date,
            str(t.session_count),
            str(t.user_turns),
            str(t.message_count),
            _fmt_tokens(t.total_tokens),
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
    from .collectors import create_default_registry

    try:
        db = Database()
        registry = create_default_registry()
        registry.sync_all(db)
        overview = aggregator.get_today_overview(db)
        today_sessions = aggregator.get_today_sessions(db)
        live_sessions = registry.get_live_sessions()
        aggregator.merge_live_into_overview(overview, live_sessions, today_sessions)
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


# ── pricing subcommands ────────────────────────────────────────────


@pricing_app.command("list")
def pricing_list() -> None:
    """List all model pricing (builtin + user overrides)."""
    from .pricing import _BUILTIN_PRICING, _load_user_pricing

    user = _load_user_pricing()

    table = Table(title="Model Pricing (USD per 1M tokens)")
    table.add_column("Model", style="cyan")
    table.add_column("Input", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Cache Read", justify="right")
    table.add_column("Cache Write", justify="right")
    table.add_column("Source", style="dim")

    # Show all builtin models, marking overrides
    all_models = dict(_BUILTIN_PRICING)
    all_models.update(user)

    for model in sorted(all_models):
        p = all_models[model]
        if model in user and model in _BUILTIN_PRICING:
            source = "[yellow]override[/yellow]"
        elif model in user:
            source = "[green]custom[/green]"
        else:
            source = "builtin"
        table.add_row(
            model,
            f"${p[0]:.3f}",
            f"${p[1]:.3f}",
            f"${p[2]:.3f}",
            f"${p[3]:.3f}",
            source,
        )

    console.print(table)


@pricing_app.command("set", context_settings={"help_option_names": ["-h", "--help"]})
def pricing_set(
    ctx: typer.Context,
    model: str = typer.Argument(None, help="Model name (e.g. claude-opus-4-6)."),
    input_price: float = typer.Option(None, "--input", "-i", help="Input price per 1M tokens."),
    output_price: float = typer.Option(None, "--output", "-o", help="Output price per 1M tokens."),
    cache_read: float = typer.Option(0.0, "--cache-read", "-cr", help="Cache read price per 1M tokens."),
    cache_write: float = typer.Option(0.0, "--cache-write", "-cw", help="Cache write price per 1M tokens."),
) -> None:
    """Add or update pricing for a model.

    Prices are in USD per 1M tokens.
    """
    if model is None or input_price is None or output_price is None:
        console.print(ctx.get_help())
        console.print()
        console.print("[bold]Examples:[/bold]")
        console.print("  # Add a new model")
        console.print("  agentic-metric pricing set deepseek-r2 -i 0.5 -o 2.0")
        console.print()
        console.print("  # Override builtin pricing")
        console.print("  agentic-metric pricing set claude-opus-4-6 -i 4.0 -o 20.0 -cr 0.4 -cw 5.0")
        raise typer.Exit()

    from .pricing import set_user_pricing

    set_user_pricing(model, input_price, output_price, cache_read, cache_write)
    console.print(
        f"[green]Set pricing for {model}:[/green] "
        f"input=${input_price:.3f}  output=${output_price:.3f}  "
        f"cache_read=${cache_read:.3f}  cache_write=${cache_write:.3f}"
    )


@pricing_app.command("reset")
def pricing_reset(
    model: str = typer.Argument(
        None, help="Model to reset. Omit to reset all.",
    ),
    all_models: bool = typer.Option(
        False, "--all", help="Reset all user overrides.",
    ),
) -> None:
    """Reset pricing to builtin defaults."""
    from .pricing import remove_user_pricing, reset_all_user_pricing

    if all_models:
        reset_all_user_pricing()
        console.print("[green]All user pricing overrides removed.[/green]")
    elif model:
        if remove_user_pricing(model):
            console.print(f"[green]Reset {model} to builtin default.[/green]")
        else:
            console.print(f"[yellow]{model} has no user override.[/yellow]")
    else:
        console.print("[red]Specify a model name or use --all.[/red]")
        raise typer.Exit(1)
