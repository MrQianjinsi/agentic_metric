"""Claude Code collector: parse local JSONL/JSON files + live process monitoring."""

from __future__ import annotations

import json
import re
from datetime import datetime
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
        "today_user_turns",
        "today_message_count",
        "today_input_tokens",
        "today_output_tokens",
        "today_cache_read",
        "today_cache_create",
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
        self.today_user_turns = 0
        self.today_message_count = 0
        self.today_input_tokens = 0
        self.today_output_tokens = 0
        self.today_cache_read = 0
        self.today_cache_create = 0

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

        today_str = datetime.now().strftime("%Y-%m-%d")
        for raw_line in new_data.split(b"\n"):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entry = json.loads(raw_line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            self._process_entry(entry, today_str)

    @staticmethod
    def _ts_local_date(ts: str) -> str:
        """Convert ISO timestamp to local date string YYYY-MM-DD."""
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.astimezone().strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return ts[:10] if len(ts) >= 10 else ""

    def _process_entry(self, entry: dict, today_str: str) -> None:
        ts = entry.get("timestamp", "")
        if ts:
            if not self.first_ts:
                self.first_ts = ts
            self.last_ts = ts

        is_today = self._ts_local_date(ts) == today_str if ts else True
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
                if is_today:
                    self.today_user_turns += 1
                    self.today_message_count += 1
                if isinstance(content, str):
                    clean = _extract_prompt(content)
                    if clean:
                        if not self.first_prompt:
                            self.first_prompt = clean[:80]
                        self.last_prompt = clean[:80]

        elif entry_type == "assistant":
            self.message_count += 1
            if is_today:
                self.today_message_count += 1
            msg = entry.get("message", {})
            usage = msg.get("usage", {}) if isinstance(msg, dict) else {}
            if usage:
                inp = usage.get("input_tokens", 0)
                out = usage.get("output_tokens", 0)
                cr = usage.get("cache_read_input_tokens", 0)
                cw = usage.get("cache_creation_input_tokens", 0)
                self.input_tokens += inp
                self.output_tokens += out
                self.cache_read += cr
                self.cache_create += cw
                if is_today:
                    self.today_input_tokens += inp
                    self.today_output_tokens += out
                    self.today_cache_read += cr
                    self.today_cache_create += cw
            if not self.model and isinstance(msg, dict):
                self.model = msg.get("model", "")

    def to_live_session(self) -> LiveSession:
        return LiveSession(
            session_id=self.session_id,
            agent_type="claude_code",
            project_path=self.project_path,
            git_branch=self.git_branch,
            model=self.model,
            message_count=self.message_count,
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
            today_input_tokens=self.today_input_tokens,
            today_output_tokens=self.today_output_tokens,
            today_cache_read_tokens=self.today_cache_read,
            today_cache_creation_tokens=self.today_cache_create,
            today_user_turns=self.today_user_turns,
            today_message_count=self.today_message_count,
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

        # Build cwd -> list of pids (multiple sessions may share a cwd)
        cwd_to_pids: dict[str, list[int]] = {}
        for pid, cwd in pid_cwds.items():
            cwd_to_pids.setdefault(cwd, []).append(pid)

        results: list[LiveSession] = []
        active_files: set[Path] = set()

        for cwd in cwd_set:
            project_dir = self._cwd_map.get(cwd)
            if not project_dir:
                continue

            # Find most recently modified .jsonl files
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

            # Pick as many JSONL files as there are active PIDs for this CWD
            pids = cwd_to_pids.get(cwd, [])
            num_sessions = max(1, len(pids))

            for idx, jf in enumerate(jsonl_files[:num_sessions]):
                if jf in active_files:
                    continue
                active_files.add(jf)

                pid = pids[idx] if idx < len(pids) else 0

                # Get or create accumulator
                accum = self._accums.get(jf)
                if accum is None:
                    accum = _SessionAccum(jf, cwd, pid=pid)
                    self._accums[jf] = accum
                else:
                    # Update pid in case it changed across refreshes
                    accum.pid = pid

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

    @staticmethod
    def _read_session_id(jsonl_file: Path) -> str:
        """Extract the sessionId field from the first few lines of a JSONL file.

        For a subagent transcript this is the id of the session that dispatched
        it -- subagent entries carry the PARENT's sessionId, not one of their own.
        """
        try:
            with open(jsonl_file) as f:
                for i, line in enumerate(f):
                    if i > 10:
                        break
                    try:
                        entry = json.loads(line)
                        sid = entry.get("sessionId", "")
                        if sid:
                            return sid
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
                # Top-level files are the ordinary sessions. Subagent (Task tool)
                # transcripts live one level deeper, in
                #   <project>/<session-id>/subagents/*.jsonl
                # and are separate files -- their turns are NOT inlined into the
                # parent transcript, so a non-recursive glob misses their tokens
                # entirely.
                jsonl_files = list(project_dir.glob("*.jsonl"))
                jsonl_files += list(project_dir.glob("*/subagents/*.jsonl"))
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

                # A subagent transcript carries the PARENT's sessionId in every
                # entry, so that value must NOT become the row key: all of a
                # session's subagents, and the parent, would collapse into one
                # row. The file stem (e.g. "agent-<name>-<hash>") is the unique
                # id -- which is what _SessionAccum already derives, so this is
                # stated explicitly only to keep the intent obvious next to the
                # parent lookup below.
                if jsonl_file.parent.name == "subagents":
                    session_id = jsonl_file.stem
                    # NOT accum.session_id -- that is derived from the file name
                    # (see _SessionAccum.__init__), which for a subagent is the
                    # subagent's own id. The parent's id is in the entries.
                    parent_session_id = _LiveMonitor._read_session_id(jsonl_file)
                else:
                    session_id = accum.session_id
                    parent_session_id = ""

                db.upsert_session(
                    session_id,
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
                    parent_session_id=parent_session_id,
                )

                db.set_sync_state(sync_key, str(file_size))

