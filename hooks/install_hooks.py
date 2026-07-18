#!/usr/bin/env python3
"""Safely add daylog's SessionStart/Stop hooks to ~/.claude/settings.json.

Merges into whatever hooks config already exists rather than overwriting it.
Idempotent: running it twice never adds duplicate entries. Backs up the
previous settings.json before writing.

Usage:
    python3 install_hooks.py           # installs
    python3 install_hooks.py --dry-run # prints the resulting settings.json, changes nothing
    python3 install_hooks.py --uninstall
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
SCRIPT_PATH = Path(__file__).resolve().parent / "claude_session.py"


def _hook_command(event: str) -> str:
    return f"python3 {SCRIPT_PATH} {event}"


def _entry_index(hook_list: list, command: str) -> int | None:
    for i, matcher_block in enumerate(hook_list):
        for hook in matcher_block.get("hooks", []):
            if hook.get("command") == command:
                return i
    return None


def _write(settings: dict, dry_run: bool) -> None:
    output = json.dumps(settings, indent=2) + "\n"
    if dry_run:
        print(output)
        return
    if SETTINGS_PATH.exists():
        backup = SETTINGS_PATH.with_suffix(".json.bak")
        backup.write_text(SETTINGS_PATH.read_text())
        print(f"backed up existing settings to {backup}")
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(output)


def install(dry_run: bool = False) -> None:
    settings = {}
    if SETTINGS_PATH.exists():
        settings = json.loads(SETTINGS_PATH.read_text())

    hooks = settings.setdefault("hooks", {})

    for event_name, arg in (
        ("SessionStart", "session-start"),
        ("UserPromptSubmit", "user-prompt-submit"),
        ("Stop", "stop"),
        ("SessionEnd", "session-end"),
    ):
        command = _hook_command(arg)
        hook_list = hooks.setdefault(event_name, [])
        if _entry_index(hook_list, command) is None:
            hook_list.append({"matcher": "", "hooks": [{"type": "command", "command": command}]})

    _write(settings, dry_run)
    if not dry_run:
        print(f"installed daylog hooks into {SETTINGS_PATH}")


def uninstall(dry_run: bool = False) -> None:
    if not SETTINGS_PATH.exists():
        print("no settings.json found, nothing to do")
        return
    settings = json.loads(SETTINGS_PATH.read_text())
    hooks = settings.get("hooks", {})

    for event_name, arg in (
        ("SessionStart", "session-start"),
        ("UserPromptSubmit", "user-prompt-submit"),
        ("Stop", "stop"),
        ("SessionEnd", "session-end"),
    ):
        command = _hook_command(arg)
        hook_list = hooks.get(event_name, [])
        idx = _entry_index(hook_list, command)
        if idx is not None:
            hook_list.pop(idx)
        if event_name in hooks and not hooks[event_name]:
            del hooks[event_name]

    _write(settings, dry_run)
    if not dry_run:
        print(f"removed daylog hooks from {SETTINGS_PATH}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--uninstall" in args:
        uninstall(dry_run="--dry-run" in args)
    else:
        install(dry_run="--dry-run" in args)
