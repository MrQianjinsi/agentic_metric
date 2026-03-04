"""Cursor agent collector."""

from __future__ import annotations

import base64
import json
import platform
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import BaseCollector
from ..config import CURSOR_STATE_DB
from ..models import LiveSession
from ..pricing import estimate_cost, normalize_model
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


def _ms_to_iso(ms: int | None) -> str:
    """Convert millisecond timestamp to ISO 8601 string."""
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _decode_cursor_project_path(cursor_path: str) -> str:
    """Decode Cursor internal project path to actual filesystem path.

    Cursor encodes workspace paths by replacing both ``/`` and ``_`` with
    ``-``.  We use backtracking to find the first existing directory.
    """
    prefix = "/.cursor/projects/"
    idx = cursor_path.find(prefix)
    if idx < 0:
        return ""
    encoded = cursor_path[idx + len(prefix) :]
    parts = encoded.split("-")
    if not parts:
        return ""

    def _try(i: int, cur: str) -> str:
        if i == len(parts):
            try:
                return cur if Path(cur).is_dir() else ""
            except (OSError, PermissionError):
                return ""
        for sep in ("/", "_", "-"):
            result = _try(i + 1, cur + sep + parts[i])
            if result:
                return result
        return ""

    return _try(1, "/" + parts[0])


def _extract_path_from_conversation_state(cs_b64: str) -> str:
    """Extract project path from base64-encoded conversationState protobuf."""
    if not cs_b64:
        return ""
    try:
        raw = base64.b64decode(cs_b64)
    except Exception:
        return ""
    m = re.search(rb"file:///([^\x00-\x1f\x80-\xff]+)", raw)
    if not m:
        return ""
    path = "/" + m.group(1).decode()
    # Strip trailing protobuf tag bytes until we hit a real directory
    while len(path) > 6:  # at least /x/y/z
        try:
            if Path(path).is_dir():
                return path
        except (OSError, PermissionError):
            pass
        path = path[:-1]
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
        """Sync Cursor composer sessions from state.vscdb into our database."""
        if not CURSOR_STATE_DB.exists():
            return

        # Skip if state.vscdb hasn't changed since last sync
        try:
            mtime = str(CURSOR_STATE_DB.stat().st_mtime)
        except OSError:
            return
        prev_mtime = db.get_sync_state("cursor_state_db_mtime")
        if prev_mtime == mtime:
            return

        self._sync_composer_sessions(db)
        self._derive_daily_stats_from_sessions(db)
        db.commit()
        db.set_sync_state("cursor_state_db_mtime", mtime)

    def _sync_composer_sessions(self, db) -> None:
        """Read composerData + bubble data from state.vscdb and upsert."""
        try:
            src = sqlite3.connect(
                f"file:{CURSOR_STATE_DB}?mode=ro", uri=True
            )
        except sqlite3.OperationalError:
            return

        try:
            src.row_factory = sqlite3.Row
            rows = src.execute(
                "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'"
            ).fetchall()

            # Pre-fetch bubble data: tokens, model, workspace path, text
            bubble_rows = src.execute(
                "SELECT key, "
                "json_extract(value, '$.tokenCount.inputTokens') AS inp, "
                "json_extract(value, '$.tokenCount.outputTokens') AS outp, "
                "json_extract(value, '$.modelInfo.modelName') AS model, "
                "json_extract(value, '$.workspaceProjectDir') AS wpd, "
                "json_extract(value, '$.type') AS btype, "
                "json_extract(value, '$.text') AS text "
                "FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'"
            ).fetchall()
        finally:
            src.close()

        # Build per-composer bubble info
        bubble_info: dict[str, dict] = {}
        for br in bubble_rows:
            parts = br["key"].split(":", 2)
            if len(parts) != 3:
                continue
            cid = parts[1]
            info = bubble_info.get(cid)
            if info is None:
                info = {"tokens": [], "models": set(), "wpd": "",
                        "first_user_text": "", "last_user_text": ""}
                bubble_info[cid] = info
            info["tokens"].append((br["inp"] or 0, br["outp"] or 0))
            model = br["model"]
            if model and model != "default":
                info["models"].add(model)
            wpd = br["wpd"]
            if wpd and not info["wpd"]:
                info["wpd"] = wpd
            # type=1 is user message
            if br["btype"] == 1:
                text = br["text"]
                if text and isinstance(text, str) and text.strip():
                    clean = text.strip()[:80]
                    if not info["first_user_text"]:
                        info["first_user_text"] = clean
                    info["last_user_text"] = clean

        # Cache for decoded project paths
        _path_cache: dict[str, str] = {}

        # Per-model-per-date accumulators for model_daily_usage
        model_daily: dict[tuple[str, str], list[float]] = {}

        for row in rows:
            try:
                data = json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                continue

            status = data.get("status", "")
            if status not in ("completed", "aborted"):
                continue

            composer_id = data.get("composerId", "")
            if not composer_id:
                continue

            session_id = f"cursor-{composer_id}"
            cid_info = bubble_info.get(composer_id, {})

            # Timestamps
            started_at = _ms_to_iso(data.get("createdAt"))
            ended_at = _ms_to_iso(data.get("lastUpdatedAt"))

            # Model: prefer composerData, fallback to bubble modelInfo
            model_config = data.get("modelConfig") or {}
            raw_model = model_config.get("modelName", "")
            model = normalize_model(raw_model)
            if not model:
                bubble_models = cid_info.get("models", set())
                if bubble_models:
                    model = normalize_model(next(iter(bubble_models)))

            # Project path: bubble workspaceProjectDir → conversationState
            project_path = ""
            wpd = cid_info.get("wpd", "")
            if wpd:
                if wpd in _path_cache:
                    project_path = _path_cache[wpd]
                else:
                    project_path = _decode_cursor_project_path(wpd)
                    _path_cache[wpd] = project_path
            if not project_path:
                cs = data.get("conversationState", "")
                if cs:
                    if cs in _path_cache:
                        project_path = _path_cache[cs]
                    else:
                        project_path = _extract_path_from_conversation_state(cs)
                        _path_cache[cs] = project_path

            # Conversation headers
            headers = data.get("fullConversationHeadersOnly") or []
            message_count = len(headers)
            user_turns = sum(
                1 for h in headers
                if isinstance(h, dict) and h.get("type") == 1
            )

            # Name / summary / prompts
            name = data.get("name", "") or ""
            first_prompt = cid_info.get("first_user_text", "") or name[:80]
            last_prompt = cid_info.get("last_user_text", "")

            # Sum bubble tokens
            input_tokens = 0
            output_tokens = 0
            for inp, outp in cid_info.get("tokens", []):
                input_tokens += inp
                output_tokens += outp

            cost = estimate_cost(
                model, input_tokens=input_tokens, output_tokens=output_tokens
            )

            db.upsert_session(
                session_id,
                self.agent_type,
                project_path=project_path,
                model=model,
                message_count=message_count,
                user_turns=user_turns,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=cost,
                started_at=started_at,
                ended_at=ended_at,
                first_prompt=first_prompt,
                last_prompt=last_prompt,
                summary=name,
            )

            # Accumulate model daily usage
            if model and started_at:
                date_str = started_at[:10]
                key = (date_str, model)
                acc = model_daily.get(key)
                if acc is None:
                    acc = [0.0, 0.0, 0.0]
                    model_daily[key] = acc
                acc[0] += input_tokens
                acc[1] += output_tokens
                acc[2] += cost

        # Upsert model daily usage
        for (date_str, model), acc in model_daily.items():
            db.upsert_model_daily_usage(
                date_str,
                model,
                self.agent_type,
                input_tokens=int(acc[0]),
                output_tokens=int(acc[1]),
                estimated_cost_usd=acc[2],
            )

    def _derive_daily_stats_from_sessions(self, db) -> None:
        """Aggregate session data into daily_stats."""
        rows = db.conn.execute(
            """SELECT
                   substr(started_at, 1, 10) AS date,
                   COUNT(*) AS session_count,
                   SUM(message_count) AS message_count,
                   SUM(user_turns) AS user_turns,
                   SUM(input_tokens) AS input_tokens,
                   SUM(output_tokens) AS output_tokens,
                   SUM(cache_read_tokens) AS cache_read_tokens,
                   SUM(cache_creation_tokens) AS cache_creation_tokens,
                   SUM(estimated_cost_usd) AS estimated_cost_usd
               FROM sessions
               WHERE agent_type = ? AND started_at != ''
               GROUP BY date
            """,
            (self.agent_type,),
        ).fetchall()

        for r in rows:
            d = r["date"]
            if not d:
                continue
            db.upsert_daily_stats(
                d,
                self.agent_type,
                session_count=r["session_count"] or 0,
                message_count=r["message_count"] or 0,
                tool_call_count=r["user_turns"] or 0,
                input_tokens=r["input_tokens"] or 0,
                output_tokens=r["output_tokens"] or 0,
                cache_read_tokens=r["cache_read_tokens"] or 0,
                cache_creation_tokens=r["cache_creation_tokens"] or 0,
                estimated_cost_usd=r["estimated_cost_usd"] or 0,
            )
