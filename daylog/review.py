"""dl review --ai — weekly qualitative insights a template can't compute.

Gives `.claude/commands/daylog-review.md` (previously a standalone, manual-only
slash command) a real headless entry point so it can back `dl review --ai`
and the widget's insights view, not just interactive `/daylog-review` use.
Unlike the interactive slash command, the headless call has no filesystem
tools available, so the week's raw entries are serialized straight into the
prompt instead of leaving the model to read `~/.daylog/data/` itself.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from daylog.analytics import load_week
from daylog.models import Entry
from daylog.summary import _call_headless_claude

COMMANDS_DIR = Path(__file__).resolve().parent.parent / ".claude" / "commands"


def _build_review_ai_prompt(week_entries: dict[date, list[Entry]], monday: date, sunday: date) -> str:
    template_path = COMMANDS_DIR / "daylog-review.md"
    instructions = template_path.read_text() if template_path.exists() else ""

    day_blocks = []
    for d in sorted(week_entries):
        entries = week_entries[d]
        if not entries:
            continue
        lines = "\n".join(
            f"- {e.ts:%H:%M} [{e.source}/{e.category}] {e.title}" + (f" ({e.jira})" if e.jira else "")
            for e in entries
        )
        day_blocks.append(f"### {d.isoformat()} ({d.strftime('%A')})\n{lines}")
    entries_text = "\n\n".join(day_blocks) if day_blocks else "(no entries logged this week)"

    return (
        f"{instructions}\n\n"
        f"## Entries for the week of {monday.isoformat()} to {sunday.isoformat()}\n{entries_text}\n"
    )


def generate_weekly_insights(cfg: dict, monday: date) -> Optional[str]:
    """Returns the AI-generated insights text, or None if AI summaries are
    disabled/unavailable/fail — callers should treat None as "insights
    unavailable" rather than an error, matching this repo's other headless-
    Claude call sites (summary.py's generate_summary)."""
    if not cfg.get("ai_summary", {}).get("enabled", True):
        return None

    from datetime import timedelta

    sunday = monday + timedelta(days=6)
    week_entries = load_week(monday)
    prompt = _build_review_ai_prompt(week_entries, monday, sunday)
    timeout_sec = cfg.get("ai_summary", {}).get("timeout_sec", 240)
    return _call_headless_claude(prompt, timeout_sec)
