"""System tray using pystray.

On xorg (no menu support), left-click directly opens the TUI.
On backends with menu support, both clicks show the full menu.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

# Ensure GI can find system GTK typelibs (needed in conda/venv environments)
# Must be set before importing pystray, which may try the appindicator backend.
for _candidate in (
    "/usr/lib/x86_64-linux-gnu/girepository-1.0",
    "/usr/lib/aarch64-linux-gnu/girepository-1.0",
    "/usr/lib64/girepository-1.0",
    "/usr/lib/girepository-1.0",
):
    if os.path.isdir(_candidate):
        _existing = os.environ.get("GI_TYPELIB_PATH", "")
        if _candidate not in _existing:
            os.environ["GI_TYPELIB_PATH"] = (
                f"{_candidate}:{_existing}" if _existing else _candidate
            )
        break

import pystray
from pystray import Menu, MenuItem

from .icon import create_icon
from ..collectors import create_default_registry
from ..pricing import estimate_session_cost
from ..store.database import Database
from ..store import aggregator

_state = {
    "active_agents": 0,
    "today_cost": 0.0,
}


def _refresh_state() -> None:
    try:
        registry = create_default_registry()
        sessions = registry.get_live_sessions()
        _state["active_agents"] = len(sessions)
        _state["today_cost"] = sum(estimate_session_cost(s) for s in sessions)
    except Exception:
        _state["active_agents"] = 0

    try:
        db = Database()
        overview = aggregator.get_today_overview(db)
        _state["today_cost"] = max(_state["today_cost"], overview.estimated_cost_usd)
        db.close()
    except Exception:
        pass


def _open_tui(*_args) -> None:
    subprocess.Popen(
        [sys.executable, "-m", "agentic_metric", "tui"],
        start_new_session=True,
    )


def _do_sync(icon, _item) -> None:
    try:
        db = Database()
        registry = create_default_registry()
        registry.sync_all(db)
        db.close()
    except Exception:
        pass
    _refresh_state()
    icon.update_menu()


def run_tray() -> None:
    """Run system tray icon.

    Left-click: opens TUI (works on all backends including xorg).
    Right-click: shows menu (only on backends with HAS_MENU=True).
    """
    _refresh_state()

    menu = Menu(
        MenuItem(
            lambda _: f"Active: {_state['active_agents']} agents",
            None,
            enabled=False,
        ),
        MenuItem(
            lambda _: f"Today: ${_state['today_cost']:.2f}",
            None,
            enabled=False,
        ),
        Menu.SEPARATOR,
        # default=True makes this the left-click action on xorg backend
        MenuItem("Open TUI", lambda icon, item: _open_tui(), default=True),
        MenuItem("Sync Now", _do_sync),
        MenuItem("Quit", lambda icon, item: icon.stop()),
    )

    icon = pystray.Icon(
        name="agentic-metric",
        icon=create_icon(),
        title="Agentic Metric",
        menu=menu,
    )

    def _loop():
        while icon.visible:
            time.sleep(30)
            _refresh_state()
            try:
                icon.update_menu()
            except Exception:
                pass

    threading.Thread(target=_loop, daemon=True).start()
    icon.run()
