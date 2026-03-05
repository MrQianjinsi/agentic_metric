"""VS Code (Copilot Chat) session collector."""

from __future__ import annotations

import json
import platform
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import BaseCollector
from ..config import VSCODE_GLOBAL_CHAT_DIR, VSCODE_STORAGE_DIR
from ..models import LiveSession
from ..pricing import estimate_cost, normalize_copilot_model

# Helper/utility process names to exclude
_HELPER_FRAGMENTS = (
    "code-helper",
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


def _ms_to_iso(ms: int | float | None) -> str:
    """Convert millisecond timestamp to ISO 8601 string."""
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _decode_workspace_uri(folder: str) -> str:
    """Decode a VS Code folder URI to a display path.

    Handles:
    - ``file:///home/user/project`` → ``/home/user/project``
    - ``vscode-remote://ssh-remote+host/path`` → ``ssh://host:/path``
    - ``vscode-remote://attached-container+hex/path`` → ``container:/path``
    """
    if not folder:
        return ""

    parsed = urlparse(folder)
    if parsed.scheme == "file":
        return unquote(parsed.path)

    if parsed.scheme == "vscode-remote":
        netloc = unquote(parsed.netloc)
        path = unquote(parsed.path)
        m = re.match(r"ssh-remote\+(.+)", netloc)
        if m:
            return f"ssh://{m.group(1)}:{path}"
        if netloc.startswith("attached-container+"):
            return f"container:{path}"
        return f"{netloc}:{path}"

    return folder


def _decode_workspace_path(workspace_json: Path) -> str:
    """Read workspace.json and decode the folder URI to a filesystem path."""
    try:
        data = json.loads(workspace_json.read_text())
    except (OSError, json.JSONDecodeError):
        return ""
    return _decode_workspace_uri(data.get("folder", ""))


def _find_chat_session_files() -> list[tuple[Path, str]]:
    """Find all VS Code chat session files (.json and .jsonl).

    Returns list of (file_path, project_path) tuples.
    For sessions that exist in both formats, only the JSONL is returned
    (it's the newer, canonical source).
    """
    results: list[tuple[Path, str]] = []

    # Workspace storage sessions
    if VSCODE_STORAGE_DIR.is_dir():
        try:
            for ws_dir in VSCODE_STORAGE_DIR.iterdir():
                if not ws_dir.is_dir():
                    continue
                chat_dir = ws_dir / "chatSessions"
                if not chat_dir.is_dir():
                    continue
                workspace_json = ws_dir / "workspace.json"
                project_path = _decode_workspace_path(workspace_json)

                # Collect files, preferring .jsonl over .json for same session
                jsonl_stems: set[str] = set()
                jsonl_files: list[Path] = []
                json_files: list[Path] = []
                try:
                    for f in chat_dir.iterdir():
                        if f.suffix == ".jsonl":
                            jsonl_files.append(f)
                            jsonl_stems.add(f.stem)
                        elif f.suffix == ".json":
                            json_files.append(f)
                except OSError:
                    continue

                for f in jsonl_files:
                    results.append((f, project_path))
                for f in json_files:
                    if f.stem not in jsonl_stems:
                        results.append((f, project_path))
        except OSError:
            pass

    # Global/empty window sessions
    if VSCODE_GLOBAL_CHAT_DIR.is_dir():
        try:
            for f in VSCODE_GLOBAL_CHAT_DIR.iterdir():
                if f.suffix in (".json", ".jsonl"):
                    results.append((f, ""))
        except OSError:
            pass

    return results


# ── JSONL incremental state parser ──────────────────────────────────────


def _parse_jsonl_session(path: Path) -> dict | None:
    """Replay a JSONL incremental chat session into a flat dict.

    The JSONL format uses:
    - kind=0: initial snapshot (full session state)
    - kind=1: set value at path k
    - kind=2: array append at path k

    Returns a dict with keys: sessionId, creationDate, customTitle,
    lastMessageDate, requests (list of request dicts).
    """
    try:
        text = path.read_text()
    except OSError:
        return None

    state: dict = {}
    for raw_line in text.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        kind = entry.get("kind")
        v = entry.get("v")

        if kind == 0:
            # Initial snapshot
            if isinstance(v, dict):
                state = v
        elif kind == 1:
            # Set value at path
            keys = entry.get("k", [])
            if not keys:
                continue
            _set_nested(state, keys, v)
        elif kind == 2:
            # Array append at path
            keys = entry.get("k", [])
            if not keys:
                continue
            arr = _get_nested(state, keys)
            if isinstance(arr, list) and isinstance(v, list):
                arr.extend(v)

    if not state:
        return None
    return state


def _get_nested(obj: dict, keys: list) -> object:
    """Navigate into a nested dict/list by key path."""
    cur: object = obj
    for k in keys:
        if isinstance(cur, dict) and isinstance(k, str):
            cur = cur.get(k)
        elif isinstance(cur, list) and isinstance(k, int):
            if 0 <= k < len(cur):
                cur = cur[k]
            else:
                return None
        else:
            return None
    return cur


def _set_nested(obj: dict, keys: list, value: object) -> None:
    """Set a value in a nested dict/list by key path."""
    cur: object = obj
    for k in keys[:-1]:
        if isinstance(cur, dict) and isinstance(k, str):
            nxt = cur.get(k)
            if nxt is None:
                nxt = {} if isinstance(keys[keys.index(k) + 1], str) else []
                cur[k] = nxt
            cur = nxt
        elif isinstance(cur, list) and isinstance(k, int):
            if 0 <= k < len(cur):
                cur = cur[k]
            else:
                return
        else:
            return

    last = keys[-1]
    if isinstance(cur, dict) and isinstance(last, str):
        cur[last] = value
    elif isinstance(cur, list) and isinstance(last, int):
        if 0 <= last < len(cur):
            cur[last] = value


# ── Collector ───────────────────────────────────────────────────────────


class VscodeCollector(BaseCollector):
    """Collect session data from VS Code Copilot Chat."""

    @property
    def agent_type(self) -> str:
        return "vscode"

    def get_live_sessions(self) -> list[LiveSession]:
        """Detect running VS Code processes and return live sessions."""
        from ._process import get_running_cwds

        pid_cwds = get_running_cwds("code", exact=True)
        sessions: list[LiveSession] = []

        for pid, cwd in pid_cwds.items():
            cmdline = _read_cmdline(pid)
            if any(frag in cmdline for frag in _HELPER_FRAGMENTS):
                continue

            sessions.append(
                LiveSession(
                    session_id=f"vscode-{pid}",
                    agent_type="vscode",
                    pid=pid,
                    project_path=cwd,
                )
            )

        return sessions

    def sync_history(self, db) -> None:
        """Sync VS Code Copilot Chat sessions into our database."""
        session_files = _find_chat_session_files()
        if not session_files:
            return

        for file_path, project_path in session_files:
            sync_key = f"vscode_chat_mtime:{file_path}"
            try:
                mtime = str(file_path.stat().st_mtime)
            except OSError:
                continue
            prev_mtime = db.get_sync_state(sync_key)
            if prev_mtime == mtime:
                continue

            self._sync_session_file(db, file_path, project_path)
            db.set_sync_state(sync_key, mtime)

        db.commit()

    def _sync_session_file(
        self,
        db,
        file_path: Path,
        project_path: str,
    ) -> bool:
        """Parse a chat session file (.json or .jsonl) and upsert."""
        if file_path.suffix == ".jsonl":
            data = _parse_jsonl_session(file_path)
        else:
            try:
                data = json.loads(file_path.read_text())
            except (OSError, json.JSONDecodeError):
                return False

        if not data:
            return False
        return self._upsert_session_data(db, data, file_path, project_path)

    def _upsert_session_data(
        self,
        db,
        data: dict,
        file_path: Path,
        project_path: str,
    ) -> bool:
        """Extract fields from parsed session data and upsert into DB."""
        requests = data.get("requests", [])
        if not requests:
            return False

        session_id = data.get("sessionId", "") or file_path.stem

        started_at = _ms_to_iso(data.get("creationDate"))
        ended_at = _ms_to_iso(data.get("lastMessageDate"))
        # For JSONL sessions, lastMessageDate may not be a top-level field;
        # fall back to the last request's timestamp
        if not ended_at and requests:
            last_ts = requests[-1].get("timestamp")
            if last_ts:
                ended_at = _ms_to_iso(last_ts)

        user_turns = len(requests)
        message_count = user_turns * 2

        models: dict[str, int] = {}
        first_prompt = ""
        last_prompt = ""
        input_tokens = 0
        output_tokens = 0

        for req in requests:
            # Model from result.details
            result = req.get("result") or {}
            details = result.get("details", "")
            model = normalize_copilot_model(details)

            # Fallback to modelId field
            if not model:
                model_id = req.get("modelId", "") or ""
                if model_id and "/" in model_id:
                    model = model_id.split("/", 1)[1]
                elif model_id:
                    model = model_id

            if model:
                models[model] = models.get(model, 0) + 1

            # Token usage (available in newer JSONL format)
            usage = result.get("usage") or {}
            input_tokens += usage.get("promptTokens", 0)
            output_tokens += usage.get("completionTokens", 0)

            # Prompts
            msg = req.get("message") or {}
            text = msg.get("text", "") if isinstance(msg, dict) else ""
            if isinstance(text, str) and text.strip():
                clean = text.strip()[:80]
                if not first_prompt:
                    first_prompt = clean
                last_prompt = clean

        primary_model = ""
        if models:
            primary_model = max(models, key=lambda k: models[k])

        summary = data.get("customTitle", "") or ""

        cost = estimate_cost(
            primary_model, input_tokens=input_tokens, output_tokens=output_tokens,
        )

        db.upsert_session(
            session_id,
            self.agent_type,
            project_path=project_path,
            model=primary_model,
            message_count=message_count,
            user_turns=user_turns,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=cost,
            started_at=started_at,
            ended_at=ended_at,
            first_prompt=first_prompt,
            last_prompt=last_prompt,
            summary=summary,
        )

        return True
