"""Loads ~/.daylog/config.yaml, creating it with defaults on first run."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DAYLOG_HOME = Path(os.environ.get("DAYLOG_HOME", "~/.daylog")).expanduser()
CONFIG_PATH = DAYLOG_HOME / "config.yaml"
DATA_DIR = DAYLOG_HOME / "data"
SUMMARIES_DIR = DAYLOG_HOME / "summaries"
STATE_DIR = DAYLOG_HOME / "state"
HOOK_ERROR_LOG = DAYLOG_HOME / "hook-errors.log"

DEFAULT_CONFIG: dict[str, Any] = {
    "categories": [
        "coding",
        "meeting",
        "discussion",
        "review",
        "firefighting",
        "learning",
        "admin",
        "other",
    ],
    "default_duration_min": 30,
    # Ceiling for the elapsed-time-based duration guess (store.suggested_duration_min)
    # so a first log after a long uncaptured gap (lunch, overnight, an
    # unlogged meeting) doesn't produce an absurd duration.
    "default_duration_min_cap": 180,
    "claude_capture": {
        "threshold_min": 10,
        "ignore_dirs": [],
    },
    "reminder": {
        "time": "18:00",
        "enabled": True,
    },
    "calendar_sync": {
        "enabled": True,
        "backend": "eventkit",
        "sync_time": "17:45",
        "skip_all_day": True,
        "skip_declined": True,
        "min_duration_min": 10,
        "ignore_titles": ["focus", "lunch", "blocker", "hold"],
        "dedup_tolerance_min": 10,
    },
    "gapfill": {
        "min_gap_min": 15,
        "excluded_categories": ["lunch", "break"],
    },
    "working_hours": {
        "start": "09:00",
        "end": "18:00",
    },
    "ai_summary": {
        "enabled": True,
        # Headless `claude -p` calls in this repo consistently take ~2-3
        # minutes end to end, not seconds -- a short timeout just means
        # silent fallback to template_summary every time.
        "timeout_sec": 240,
    },
    "github_sync": {
        "enabled": True,
        "authored_duration_min": 30,
        "review_duration_min": 20,
        "comment_duration_min": 10,
        "timeout_sec": 20,
    },
    "checkpoint": {
        "enabled": True,
        "jira_timeout_sec": 90,
        # Off by default. The 17:45 checkpoint's Jira pull runs headless with
        # no one to approve Atlassian MCP tool prompts, so it silently does
        # nothing (safe) unless this is true. Setting it true adds
        # --dangerously-skip-permissions to that one specific subprocess call
        # — it bypasses permission checks only for that call, not your normal
        # interactive Claude Code sessions. Only enable this if you're
        # comfortable with headless, unattended MCP tool use on a timer.
        "jira_skip_permissions": False,
        "outlook_timeout_sec": 90,
        # Same tradeoff as jira_skip_permissions above, for the Outlook
        # calendar backend's headless Microsoft 365 MCP call (only used when
        # calendar_sync.backend is "outlook").
        "outlook_skip_permissions": False,
    },
    "morning_brief": {
        # Off by default -- this is an opt-in feature (install.sh offers it).
        "enabled": False,
        "delivery": "notes",  # "notes" (AppleScript/JXA into Notes.app) or "email" (Gmail MCP)
        "recipient_email": None,  # only used when delivery is "email"
        # A launchd StartInterval job polls `dl morning-brief` roughly every
        # 15 min rather than firing at a fixed clock time, so it goes out
        # shortly after you next open/wake your laptop rather than at a
        # fixed hour that might catch your laptop still asleep. This guards
        # against firing before you're plausibly at your desk if the poller
        # happens to catch an early wake (e.g. laptop briefly opened at 3am).
        "earliest_hour": 6,
        "timeout_sec": 240,
        # Same unattended-MCP tradeoff as jira_skip_permissions, for the
        # "email" delivery mode's headless Gmail MCP call.
        "email_skip_permissions": False,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def ensure_dirs() -> None:
    for d in (DAYLOG_HOME, DATA_DIR, SUMMARIES_DIR, STATE_DIR):
        d.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any]:
    ensure_dirs()
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(yaml.safe_dump(DEFAULT_CONFIG, sort_keys=False))
        return DEFAULT_CONFIG
    try:
        user_config = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    except yaml.YAMLError:
        return DEFAULT_CONFIG
    return _deep_merge(DEFAULT_CONFIG, user_config)
