"""Morning digest: yesterday's AI-polished standup, delivered automatically
shortly after you next open/wake your laptop (not at a fixed clock time —
see the `earliest_hour` + idempotency-marker logic below, and
reminders/com.daylog.morningbrief.plist.template for the polling launchd
job). Delivered to Notes.app by default, or email via the Gmail MCP
connector if `morning_brief.delivery: "email"` is configured.

Entirely best-effort and local, matching this repo's other automated side
effects (hooks, checkpoint, calendar sync) — delivery failing here must
never be loud or block anything else. Building the standup text itself
needs no MCP/network access (it's the same headless `claude -p` +
daylog-standup.md prompt path `dl summary --ai` already uses); only the
optional "email" delivery mode needs MCP.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from daylog.config import DAYLOG_HOME, STATE_DIR, ensure_dirs

NOTE_SCRIPT = Path(__file__).resolve().parent / "scripts" / "write_note.jxa"
MORNING_BRIEF_LOG = DAYLOG_HOME / "morning-brief.log"
_MARKER_NAME = "morning-brief-last-sent.json"


def _log(line: str) -> None:
    try:
        ensure_dirs()
        with open(MORNING_BRIEF_LOG, "a") as f:
            f.write(f"{datetime.now().isoformat()} {line}\n")
    except Exception:
        pass


def _marker_path() -> Path:
    return STATE_DIR / _MARKER_NAME


def _already_sent_today(today: date) -> bool:
    marker = _marker_path()
    if not marker.exists():
        return False
    try:
        data = json.loads(marker.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    return data.get("date") == today.isoformat()


def _mark_sent(today: date, delivery: str) -> None:
    ensure_dirs()
    _marker_path().write_text(json.dumps({"date": today.isoformat(), "delivery": delivery}))


def _write_note(title: str, body: str) -> bool:
    """Best-effort delivery via Notes.app (see scripts/write_note.jxa —
    flagged there as needing a live verification run before relying on it
    unattended). Checks stdout content, not just exit code: the JXA script
    catches its own exceptions and always exits 0, returning "ok" only on
    genuine success."""
    if not shutil.which("osascript") or not NOTE_SCRIPT.exists():
        return False
    try:
        result = subprocess.run(
            ["osascript", "-l", "JavaScript", str(NOTE_SCRIPT), title, body],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "ok"


def _send_email(subject: str, body: str, recipient: str, timeout_sec: int, skip_permissions: bool) -> bool:
    """Delivery via the Gmail MCP connector, same headless-claude-with-MCP
    pattern as the Jira/Outlook checkpoints — opt-in only
    (morning_brief.delivery: "email"), since unlike Notes delivery this
    needs unattended MCP tool use, same tradeoff as checkpoint.jira_skip_permissions.
    """
    if not shutil.which("claude"):
        _log("email delivery skipped: claude not on PATH")
        return False
    prompt = (
        "Send an email via the Gmail MCP connector. Send exactly this content, "
        "verbatim — do not summarize, edit, or add commentary of your own.\n\n"
        f"To: {recipient}\nSubject: {subject}\n\n{body}"
    )
    command = ["claude", "-p", prompt, "--output-format", "text"]
    if skip_permissions:
        command.append("--dangerously-skip-permissions")
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout_sec)
    except (subprocess.TimeoutExpired, OSError) as exc:
        _log(f"email delivery failed: {exc!r}")
        return False
    return result.returncode == 0


def run_morning_brief(cfg: dict, now: Optional[datetime] = None) -> dict:
    """Best-effort, never raises. Returns a dict describing what happened
    (for `dl morning-brief`'s own console output / logging) — callers
    shouldn't need to inspect it beyond `enabled`/`sent`.

    Meant to be polled every ~15 min by launchd (StartInterval, not a fixed
    clock time) so it fires shortly after the laptop is next awake. Each
    call is cheap and idempotent: no-ops if already sent today, or if it's
    before `earliest_hour` (guards against an early/spurious wake).
    """
    mb_cfg = cfg.get("morning_brief", {})
    if not mb_cfg.get("enabled", False):
        return {"enabled": False}

    now = now or datetime.now().astimezone()
    today = now.date()

    if _already_sent_today(today):
        return {"enabled": True, "sent": False, "reason": "already sent today"}

    earliest_hour = mb_cfg.get("earliest_hour", 6)
    if now.hour < earliest_hour:
        return {"enabled": True, "sent": False, "reason": f"before earliest_hour ({earliest_hour}:00)"}

    from daylog.summary import generate_summary

    yesterday = today - timedelta(days=1)
    text = generate_summary(yesterday, cfg, ai=True)
    title = f"daylog — {yesterday.isoformat()} standup"

    delivery = mb_cfg.get("delivery", "notes")
    if delivery == "email":
        recipient = mb_cfg.get("recipient_email")
        if not recipient:
            _log("email delivery skipped: morning_brief.recipient_email not set")
            return {"enabled": True, "delivery": "email", "sent": False, "reason": "no recipient configured"}
        sent = _send_email(
            title,
            text,
            recipient,
            timeout_sec=mb_cfg.get("timeout_sec", 240),
            skip_permissions=mb_cfg.get("email_skip_permissions", False),
        )
    else:
        sent = _write_note(title, text)

    _log(f"morning brief via {delivery}: {'sent' if sent else 'failed'}")
    if sent:
        # Only mark on success -- a transient failure (Notes.app scripting
        # hiccup, network blip) should retry on the next poll, not give up
        # silently for the rest of the day.
        _mark_sent(today, delivery)

    return {"enabled": True, "delivery": delivery, "sent": sent}
