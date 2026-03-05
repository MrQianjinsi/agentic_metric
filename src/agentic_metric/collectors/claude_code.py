"""Claude Code collector: parse local JSONL/JSON files + live process monitoring."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..config import PROJECTS_DIR
from ..models import LiveSession
from ..pricing import estimate_cost
from . import BaseCollector
from ._process import get_running_cwds


# ── Helpers ──────────────────────────────────────────────────────────────


def _extract_prompt(content: str) -> str:
    """Extract meaningful user prompt from message content, stripping system noise."""
    # Strip XML-like tags
    clean = re.sub(r"<[^>]+>", "", content).strip()
    # Skip known noise prefixes
    for prefix in ("Caveat:", "login"):
        if clean.startswith(prefix):
            lines = [line.strip() for line in clean.split("\n") if line.strip()]
            for line in lines:
                skip = False
                for p in ("Caveat:", "login", "init"):
                    if line.startswith(p):
                        skip = True
                        break
                if not skip and len(line) > 2:
                    return line
            return ""
    return clean


# ── Incremental JSONL accumulator ────────────────────────────────────────


class _SessionAccum:
    """Accumulator for incremental parsing of a single session .jsonl file.

    Tracks byte offset so repeated calls only parse newly appended data.
    Builds LiveSession objects with agent_type='claude_code'.
    """

    __slots__ = (
        "file_path",
        "project_path",
        "session_id",
        "pid",
        "offset",
        "user_turns",
        "message_count",
        "input_tokens",
        "output_tokens",
        "cache_read",
        "cache_create",
        "first_ts",
        "last_ts",
        "first_prompt",
        "last_prompt",
        "git_branch",
        "model",
    )

    def __init__(self, file_path: Path, project_path: str, pid: int = 0) -> None:
        self.file_path = file_path
        self.project_path = project_path
        self.session_id = file_path.stem
        self.pid = pid
        self.offset = 0
        self.user_turns = 0
        self.message_count = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read = 0
        self.cache_create = 0
        self.first_ts = ""
        self.last_ts = ""
        self.first_prompt = ""
        self.last_prompt = ""
        self.git_branch = ""
        self.model = ""

    def read_new_lines(self) -> None:
        """Read only bytes appended since last call."""
        try:
            size = self.file_path.stat().st_size
            if size <= self.offset:
                return
            with open(self.file_path, "rb") as f:
                f.seek(self.offset)
                new_data = f.read()
            self.offset = size
        except OSError:
            return

        for raw_line in new_data.split(b"\n"):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entry = json.loads(raw_line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            self._process_entry(entry)

    def _process_entry(self, entry: dict) -> None:
        ts = entry.get("timestamp", "")
        if ts:
            if not self.first_ts:
                self.first_ts = ts
            self.last_ts = ts

        entry_type = entry.get("type", "")

        if entry_type == "user":
            if not self.git_branch:
                self.git_branch = entry.get("gitBranch", "")
            msg = entry.get("message", {})
            content = msg.get("content", "") if isinstance(msg, dict) else ""
            # tool_result entries also have type="user"; only count real human input
            is_tool_result = isinstance(content, list) and any(
                isinstance(c, dict) and c.get("type") == "tool_result"
                for c in content
            )
            if not is_tool_result:
                self.user_turns += 1
                self.message_count += 1
                if isinstance(content, str):
                    clean = _extract_prompt(content)
                    if clean:
                        if not self.first_prompt:
                            self.first_prompt = clean[:80]
                        self.last_prompt = clean[:80]

        elif entry_type == "assistant":
            self.message_count += 1
            msg = entry.get("message", {})
            usage = msg.get("usage", {}) if isinstance(msg, dict) else {}
            if usage:
                self.input_tokens += usage.get("input_tokens", 0)
                self.output_tokens += usage.get("output_tokens", 0)
                self.cache_read += usage.get("cache_read_input_tokens", 0)
                self.cache_create += usage.get("cache_creation_input_tokens", 0)
            if not self.model and isinstance(msg, dict):
                self.model = msg.get("model", "")

    def to_live_session(self) -> LiveSession:
        return LiveSession(
            session_id=self.session_id,
            agent_type="claude_code",
            project_path=self.project_path,
            git_branch=self.git_branch,
            model=self.model,
            user_turns=self.user_turns,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read_tokens=self.cache_read,
            cache_creation_tokens=self.cache_create,
            started=self.first_ts,
            last_active=self.last_ts,
            first_prompt=self.first_prompt,
            last_prompt=self.last_prompt,
            pid=self.pid,
        )


# ── Live monitor ─────────────────────────────────────────────────────────


class _LiveMonitor:
    """Monitors running Claude Code sessions with incremental JSONL parsing.

    Uses process detection to find running ``claude`` processes, maps their
    CWDs to PROJECTS_DIR subdirectories, then incrementally parses the
    most-recently-modified .jsonl file for each active project.

    Designed for ~1 s refresh cadence: first call does full parse,
    subsequent calls only read newly appended bytes.
    """

    def __init__(self) -> None:
        # cwd -> project_dir mapping (rebuilt when unknown cwds appear)
        self._cwd_map: dict[str, Path] = {}
        self._cwd_map_built = False
        # file_path -> accumulator (persists across refreshes)
        self._accums: dict[Path, _SessionAccum] = {}

    def refresh(self) -> list[LiveSession]:
        """Return currently running sessions. Fast on repeated calls."""
        pid_cwds: dict[int, str] = get_running_cwds("claude", exact=True)
        if not pid_cwds:
            return []

        cwd_set = set(pid_cwds.values())

        # Rebuild cwd map if we see unknown cwds
        if not self._cwd_map_built or not cwd_set.issubset(self._cwd_map.keys()):
            self._build_cwd_map()

        # Build cwd -> pid mapping (if multiple pids share a cwd, pick one)
        cwd_to_pid: dict[str, int] = {}
        for pid, cwd in pid_cwds.items():
            cwd_to_pid[cwd] = pid

        results: list[LiveSession] = []
        active_files: set[Path] = set()

        for cwd in cwd_set:
            project_dir = self._cwd_map.get(cwd)
            if not project_dir:
                continue

            # Find most recently modified .jsonl
            try:
                jsonl_files = sorted(
                    project_dir.glob("*.jsonl"),
                    key=lambda f: f.stat().st_mtime,
                    reverse=True,
                )
            except OSError:
                continue
            if not jsonl_files:
                continue

            latest = jsonl_files[0]
            if latest in active_files:
                continue
            active_files.add(latest)

            # Get or create accumulator
            accum = self._accums.get(latest)
            if accum is None:
                accum = _SessionAccum(latest, cwd, pid=cwd_to_pid.get(cwd, 0))
                self._accums[latest] = accum
            else:
                # Update pid in case it changed across refreshes
                accum.pid = cwd_to_pid.get(cwd, accum.pid)

            accum.read_new_lines()
            if accum.user_turns > 0:
                results.append(accum.to_live_session())

        # Prune stale accumulators
        stale = [k for k in self._accums if k not in active_files]
        for k in stale:
            del self._accums[k]

        results.sort(key=lambda s: s.last_active, reverse=True)
        return results

    def _build_cwd_map(self) -> None:
        """Map real CWDs to PROJECTS_DIR subdirectories by reading JSONL headers."""
        self._cwd_map.clear()
        if not PROJECTS_DIR.exists():
            return
        for project_dir in PROJECTS_DIR.iterdir():
            if not project_dir.is_dir():
                continue
            try:
                jsonl_files = sorted(
                    project_dir.glob("*.jsonl"),
                    key=lambda f: f.stat().st_mtime,
                    reverse=True,
                )
            except OSError:
                continue
            if not jsonl_files:
                continue
            real_cwd = self._read_cwd(jsonl_files[0])
            if real_cwd:
                self._cwd_map[real_cwd] = project_dir
        self._cwd_map_built = True

    @staticmethod
    def _read_cwd(jsonl_file: Path) -> str:
        """Extract the cwd field from the first few lines of a JSONL file."""
        try:
            with open(jsonl_file) as f:
                for i, line in enumerate(f):
                    if i > 10:
                        break
                    try:
                        entry = json.loads(line)
                        cwd = entry.get("cwd", "")
                        if cwd:
                            return cwd
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass
        return ""


# ── Collector implementation ─────────────────────────────────────────────


class ClaudeCodeCollector(BaseCollector):
    """Collector for Claude Code agent data.

    - Live sessions: process detection + incremental JSONL parsing
    - History sync: stats-cache.json, sessions-index.json, and JSONL token data
    """

    agent_type = "claude_code"

    def __init__(self) -> None:
        self._monitor = _LiveMonitor()

    def get_live_sessions(self) -> list[LiveSession]:
        """Return currently active Claude Code sessions."""
        return self._monitor.refresh()

    def sync_history(self, db) -> None:
        """Sync Claude Code history into the database.

        Parses three data sources:
        1. ``stats-cache.json`` -- daily_stats and model_daily_usage
        2. ``sessions-index.json`` -- session metadata (per project)
        3. ``.jsonl`` files -- per-session token data (incremental via sync_state)
        """
        self._sync_sessions_index(db)
        self._sync_jsonl_tokens(db)
        db.commit()

    # ── sessions-index.json ──────────────────────────────────────

    def _sync_sessions_index(self, db) -> None:
        """Parse all sessions-index.json files under PROJECTS_DIR."""
        if not PROJECTS_DIR.exists():
            return

        for index_file in PROJECTS_DIR.glob("*/sessions-index.json"):
            try:
                data = json.loads(index_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            for entry in data.get("entries", []):
                session_id = entry.get("sessionId", "")
                if not session_id:
                    continue

                created = entry.get("created", "")
                modified = entry.get("modified", "")

                db.upsert_session(
                    session_id,
                    self.agent_type,
                    project_path=entry.get("projectPath", ""),
                    git_branch=entry.get("gitBranch", ""),
                    message_count=entry.get("messageCount", 0),
                    started_at=created,
                    ended_at=modified,
                    summary=entry.get("summary", ""),
                )

    # ── JSONL token scanning ─────────────────────────────────────

    def _sync_jsonl_tokens(self, db) -> None:
        """Scan .jsonl files for per-session token data.

        Uses db sync_state to track which files/offsets have already been
        processed, making incremental re-syncs cheap.
        """
        if not PROJECTS_DIR.exists():
            return

        # Load previously processed offsets: "cc_jsonl:<filepath>" -> byte offset
        sync_prefix = "cc_jsonl:"

        for project_dir in PROJECTS_DIR.iterdir():
            if not project_dir.is_dir():
                continue

            try:
                jsonl_files = list(project_dir.glob("*.jsonl"))
            except OSError:
                continue

            for jsonl_file in jsonl_files:
                sync_key = f"{sync_prefix}{jsonl_file}"
                prev_offset_str = db.get_sync_state(sync_key)
                prev_offset = int(prev_offset_str) if prev_offset_str else 0

                try:
                    file_size = jsonl_file.stat().st_size
                except OSError:
                    continue

                if file_size <= prev_offset:
                    continue

                # Build an accumulator starting from the previous offset
                accum = _SessionAccum(jsonl_file, project_path=str(project_dir))
                # First pass: read everything from scratch to get full picture
                # (we need totals, not deltas, for upsert)
                accum.read_new_lines()

                if accum.user_turns == 0:
                    # Mark as processed even if empty
                    db.set_sync_state(sync_key, str(file_size))
                    continue

                cost = estimate_cost(
                    accum.model,
                    input_tokens=accum.input_tokens,
                    output_tokens=accum.output_tokens,
                    cache_read_tokens=accum.cache_read,
                    cache_creation_tokens=accum.cache_create,
                )

                # Read the cwd from the JSONL to get the real project path
                real_cwd = _LiveMonitor._read_cwd(jsonl_file)
                project_path = real_cwd if real_cwd else str(project_dir)

                db.upsert_session(
                    accum.session_id,
                    self.agent_type,
                    project_path=project_path,
                    git_branch=accum.git_branch,
                    model=accum.model,
                    message_count=accum.message_count,
                    user_turns=accum.user_turns,
                    input_tokens=accum.input_tokens,
                    output_tokens=accum.output_tokens,
                    cache_read_tokens=accum.cache_read,
                    cache_creation_tokens=accum.cache_create,
                    estimated_cost_usd=cost,
                    started_at=accum.first_ts,
                    ended_at=accum.last_ts,
                    first_prompt=accum.first_prompt,
                    last_prompt=accum.last_prompt,
                )

                db.set_sync_state(sync_key, str(file_size))

