"""Cross-platform process detection (Linux/macOS)."""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path


def find_pids(process_name: str, exact: bool = True) -> list[int]:
    """Find PIDs matching a process name.

    Args:
        process_name: Name to search for.
        exact: If True, match exact name (pgrep -x). If False, match pattern (pgrep -f).
    """
    try:
        flag = "-x" if exact else "-f"
        result = subprocess.run(
            ["pgrep", flag, process_name],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            return []
        return [int(pid.strip()) for pid in result.stdout.strip().split("\n") if pid.strip()]
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        return []


def get_pid_cwd(pid: int) -> str:
    """Get the working directory of a process by PID. Cross-platform."""
    system = platform.system()

    if system == "Linux":
        try:
            return str(Path(f"/proc/{pid}/cwd").resolve())
        except (OSError, PermissionError):
            return ""

    elif system == "Darwin":
        try:
            result = subprocess.run(
                ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            for line in result.stdout.split("\n"):
                if line.startswith("n") and line[1:].startswith("/"):
                    return line[1:]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return ""

    return ""


def get_running_cwds(process_name: str, exact: bool = True) -> dict[int, str]:
    """Return {pid: cwd} for all matching processes."""
    result: dict[int, str] = {}
    for pid in find_pids(process_name, exact=exact):
        cwd = get_pid_cwd(pid)
        if cwd:
            result[pid] = cwd
    return result
