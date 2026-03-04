"""Cursor agent collector."""

from __future__ import annotations

import platform
import subprocess

from . import BaseCollector
from ..models import LiveSession
from ._process import get_running_cwds

# Helper/utility process names to exclude
_HELPER_FRAGMENTS = (
    "cursor-helper",
    "cursorsearch",
    "crashpad",
    "gpu-process",
    "utility",
    "zygote",
)


def _read_cmdline(pid: int) -> str:
    """Read the command line of a process. Cross-platform."""
    system = platform.system()
    if system == "Linux":
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                return f.read().decode("utf-8", errors="replace").lower()
        except (OSError, PermissionError):
            return ""
    elif system == "Darwin":
        try:
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True, text=True, timeout=3,
            )
            return result.stdout.strip().lower()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return ""
    return ""


class CursorCollector(BaseCollector):
    """Collect live session data from Cursor editor processes."""

    @property
    def agent_type(self) -> str:
        return "cursor"

    def get_live_sessions(self) -> list[LiveSession]:
        """Detect running Cursor processes and return live sessions."""
        pid_cwds = get_running_cwds("cursor", exact=False)
        sessions: list[LiveSession] = []

        for pid, cwd in pid_cwds.items():
            cmdline = _read_cmdline(pid)
            if any(frag in cmdline for frag in _HELPER_FRAGMENTS):
                continue

            sessions.append(
                LiveSession(
                    session_id=f"cursor-{pid}",
                    agent_type="cursor",
                    pid=pid,
                    project_path=cwd,
                )
            )

        return sessions

    def sync_history(self, db) -> None:
        """Sync historical Cursor data into the database.

        Currently a no-op: Cursor does not store per-request token
        usage data locally in an easily accessible format.
        """
        pass
