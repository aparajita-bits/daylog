"""dl checkpoint: end-of-workday automated pull.

Runs calendar sync (existing sweep), GitHub PR reviews (gh CLI, fully
deterministic/automated), and Jira ticket activity (headless Claude +
Atlassian MCP, unattended) — then regenerates the AI summary with
everything included. Folded into the existing 17:45 launchd slot in place
of a bare `dl calendar-sync` call.

The Jira step is a deliberate, explicit trade-off: unattended headless tool
use (Bash + MCP) with no one watching. The default `dl backfill` path keeps
Jira interactive for exactly this reason; this command exists because it
was explicitly asked for. See widget/README.md-style troubleshooting notes
in README.md's Evening checkpoint section for how to verify it's actually
working before trusting it unattended.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import date, datetime
from pathlib import Path

from daylog.config import DAYLOG_HOME, ensure_dirs

COMMANDS_DIR = Path(__file__).resolve().parent.parent / ".claude" / "commands"
CHECKPOINT_LOG = DAYLOG_HOME / "checkpoint.log"


def _log(line: str) -> None:
    try:
        ensure_dirs()
        with open(CHECKPOINT_LOG, "a") as f:
            f.write(f"{datetime.now().isoformat()} {line}\n")
    except Exception:
        pass


def _run_headless_prompt(prompt_filename: str, timeout_sec: int, skip_permissions: bool, log_prefix: str) -> bool:
    """Shared plumbing behind every headless `claude -p <prompt file>
    [--dangerously-skip-permissions]` checkpoint step (Jira, Outlook,
    Confluence, morning-brief all use this). Best-effort, never raises.
    Returns True if the call completed (regardless of what it found/
    imported) — False means it couldn't even run (Claude Code missing,
    prompt file missing, timed out).

    Without `skip_permissions`, this reliably does nothing useful — headless
    mode has no one to approve MCP tool prompts, so it just reports that and
    stops (verified: it fails safely, doesn't hang).
    """
    if not shutil.which("claude"):
        _log(f"{log_prefix} skipped: claude not on PATH")
        return False
    prompt_path = COMMANDS_DIR / prompt_filename
    if not prompt_path.exists():
        _log(f"{log_prefix} skipped: {prompt_filename} not found")
        return False

    command = ["claude", "-p", prompt_path.read_text(), "--output-format", "text"]
    if skip_permissions:
        command.append("--dangerously-skip-permissions")

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        _log(f"{log_prefix} failed: {exc!r}")
        return False

    output = (result.stdout or "").strip()
    _log(f"{log_prefix} (exit {result.returncode}): {output[:500]}")
    return result.returncode == 0


def run_jira_checkpoint(timeout_sec: int = 90, skip_permissions: bool = False) -> bool:
    """See _run_headless_prompt for the shared contract. Set
    `checkpoint.jira_skip_permissions: true` in config.yaml to let this run
    unattended (Atlassian MCP)."""
    return _run_headless_prompt("daylog-checkpoint.md", timeout_sec, skip_permissions, "jira checkpoint")


def run_outlook_checkpoint(timeout_sec: int = 90, skip_permissions: bool = False) -> bool:
    """See _run_headless_prompt for the shared contract. Only invoked when
    `calendar_sync.backend: "outlook"` — set `checkpoint.outlook_skip_permissions:
    true` in config.yaml to let this run unattended (Microsoft 365 MCP)."""
    return _run_headless_prompt("daylog-outlook-checkpoint.md", timeout_sec, skip_permissions, "outlook checkpoint")


def run_checkpoint(day: date, cfg: dict) -> dict:
    from daylog.calendar_sync import calendar_sync
    from daylog.github_sync import sync_prs
    from daylog.summary import generate_summary

    checkpoint_cfg = cfg.get("checkpoint", {})
    if not checkpoint_cfg.get("enabled", True):
        return {"enabled": False}

    cal_entries = calendar_sync(day, cfg)
    github_entries = sync_prs(day, cfg)

    result = {
        "enabled": True,
        "calendar": len(cal_entries),
        "github": len(github_entries),
    }

    if cfg.get("calendar_sync", {}).get("backend") == "outlook":
        result["outlook_ran"] = run_outlook_checkpoint(
            checkpoint_cfg.get("outlook_timeout_sec", 90),
            skip_permissions=checkpoint_cfg.get("outlook_skip_permissions", False),
        )

    result["jira_ran"] = run_jira_checkpoint(
        checkpoint_cfg.get("jira_timeout_sec", 90),
        skip_permissions=checkpoint_cfg.get("jira_skip_permissions", False),
    )
    generate_summary(day, cfg, ai=True)

    return result
