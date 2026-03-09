# Changelog

## v0.1.8

### Bug Fixes

- **Fix multiple sessions in same directory only detecting one as active**: `cwd_to_pid` dict was overwriting duplicate CWDs; now tracks all PIDs per CWD and picks the corresponding number of recent JSONL files.
- **Fix closed sessions incorrectly marked as active**: The agent-type fallback logic (designed for VS Code's PID-based session IDs) was triggering for Claude Code when a new session hadn't synced to DB yet, causing unrelated closed sessions to show a green active dot.

## v0.1.7

### New Features

- **CLI pricing management**: New `agentic-metric pricing` subcommands (`list` / `set` / `reset`) for customizing model pricing. Overrides are stored in `pricing.json` and take precedence over built-in defaults.
- **Model family fallback pricing**: Unknown models now automatically fall back to family-level pricing (e.g. `claude-sonnet-*`), instead of always defaulting to the most expensive model.

### Bug Fixes

- **Fix cross-day session token over-counting**: Sessions spanning midnight (e.g. started yesterday, still active today) now correctly show today-only token counts in the Today page, History page, and CLI output.
- **Truncate long project/branch names in TUI**: Prevents table layout overflow when project paths or branch names are too long.
- **Cross-day session start time display**: Sessions spanning midnight now show a `MM-DD` date prefix on start times for clarity.

## v0.1.6

- Improve OpenCode live session detection.

## v0.1.5

- Remove Cursor support (Cursor stopped writing local token data).
- Simplify Agent Data Coverage docs.

## v0.1.4

- Add Qwen Code collector for tracking qwen-code CLI sessions.
- Enable shell completion and `-h` help shorthand.

## v0.1.3

- Add `--version` / `-v` flag.
- Fix History tab sort order: chart oldest→newest, table newest→oldest.
- Fix SQLite cross-thread error in sync worker.
- Unify live data merging across CLI and TUI.

## v0.1.2

- Initial release with TUI, CLI, and system tray support.
- Collectors: Claude Code, Codex, VS Code, OpenCode.
