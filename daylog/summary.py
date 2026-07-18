"""dl summary — template day summary, or --ai Claude-polished version with fallback.

Numbers are always computed in Python (see compute_day_stats) and handed to the
LLM as facts; the model is never asked to do arithmetic.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from daylog import store
from daylog.config import SUMMARIES_DIR, ensure_dirs
from daylog.models import Entry
from daylog.standup import build_standup

COMMANDS_DIR = Path(__file__).resolve().parent.parent / ".claude" / "commands"


def _fmt_h(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h}h{m}m" if m else f"{h}h"


def compute_day_stats(entries: list[Entry]) -> dict:
    by_category: dict[str, int] = {}
    by_jira: dict[str, int] = {}
    for e in entries:
        by_category[e.category] = by_category.get(e.category, 0) + e.duration_min
        if e.jira:
            by_jira[e.jira] = by_jira.get(e.jira, 0) + e.duration_min
    return {
        "total_min": sum(e.duration_min for e in entries),
        "by_category": by_category,
        "by_jira": by_jira,
    }


def template_summary(entries: list[Entry], day: date) -> str:
    if not entries:
        return f"# {day.isoformat()}\n\n(nothing logged)"

    stats = compute_day_stats(entries)
    lines = [f"# {day.isoformat()}", ""]

    by_jira: dict[str, list[Entry]] = {}
    others: list[Entry] = []
    for e in entries:
        if e.jira:
            by_jira.setdefault(e.jira, []).append(e)
        else:
            others.append(e)

    for jira_key, group in sorted(by_jira.items()):
        total = sum(e.duration_min for e in group)
        titles = "; ".join(dict.fromkeys(e.title for e in group))
        lines.append(f"- {titles} ({jira_key}, {_fmt_h(total)})")
    for e in others:
        lines.append(f"- {e.title} ({_fmt_h(e.duration_min)})")

    lines.append("")
    cat_line = ", ".join(
        f"{c} {_fmt_h(m)}" for c, m in sorted(stats["by_category"].items(), key=lambda kv: -kv[1])
    )
    lines.append(f"Total: {_fmt_h(stats['total_min'])} — {cat_line}")
    return "\n".join(lines)


def _build_ai_prompt(entries: list[Entry], day: date, stats: dict) -> str:
    template_path = COMMANDS_DIR / "daylog-standup.md"
    instructions = template_path.read_text() if template_path.exists() else ""
    entries_text = "\n".join(
        f"- {e.ts:%H:%M} [{e.source}/{e.category}] {e.title}" + (f" ({e.jira})" if e.jira else "")
        for e in entries
    ) or "(no entries logged today)"
    stats_text = (
        f"Total: {_fmt_h(stats['total_min'])}\n"
        + "\n".join(f"{c}: {_fmt_h(m)}" for c, m in stats["by_category"].items())
    )
    return (
        f"{instructions}\n\n"
        f"## Raw entries for {day.isoformat()}\n{entries_text}\n\n"
        f"## Computed stats (use these numbers exactly, do not recompute)\n{stats_text}\n"
    )


def _call_headless_claude(prompt: str, timeout_sec: int) -> Optional[str]:
    if not shutil.which("claude"):
        return None
    try:
        result = subprocess.run(
            [
                "claude",
                "-p",
                prompt,
                "--output-format",
                "text",
                # Pure text generation from the prompt we already built --
                # no need to read/search the filesystem, and letting it try
                # just adds latency.
                "--disallowedTools",
                "Read,Glob,Grep,Bash,WebFetch,WebSearch,Edit,Write,NotebookEdit,Agent,Skill",
            ],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.strip()


def _build_standup_ai_prompt(
    y_entries: list[Entry], t_entries: list[Entry], yesterday: date, today: date
) -> str:
    template_path = COMMANDS_DIR / "daylog-standup.md"
    instructions = template_path.read_text() if template_path.exists() else ""

    def _entries_text(entries: list[Entry]) -> str:
        return "\n".join(
            f"- {e.ts:%H:%M} [{e.source}/{e.category}] {e.title}" + (f" ({e.jira})" if e.jira else "")
            for e in entries
        ) or "(no entries logged)"

    return (
        f"{instructions}\n\n"
        f"## Yesterday's entries ({yesterday.isoformat()})\n{_entries_text(y_entries)}\n\n"
        f"## Today's entries ({today.isoformat()})\n{_entries_text(t_entries)}\n"
    )


def generate_standup(cfg: dict, ai: bool = False, today: Optional[date] = None) -> str:
    """Yesterday + today, copy-paste ready. `daylog-standup.md` is the single
    source of truth for the AI-polished version regardless of entry point
    (this function, or `dl summary --ai`'s single-day equivalent); the
    deterministic `standup.build_standup` template is always the fallback,
    used as-is when ai=False or the headless call is unavailable/fails."""
    today = today or date.today()
    yesterday = today - timedelta(days=1)
    y_entries = store.read_entries(yesterday)
    t_entries = store.read_entries(today)

    text = None
    if ai and cfg.get("ai_summary", {}).get("enabled", True):
        prompt = _build_standup_ai_prompt(y_entries, t_entries, yesterday, today)
        timeout_sec = cfg.get("ai_summary", {}).get("timeout_sec", 240)
        text = _call_headless_claude(prompt, timeout_sec)

    if text is None:
        text = build_standup(y_entries, t_entries)
    return text


def generate_summary(day: date, cfg: dict, ai: bool = False) -> str:
    entries = store.read_entries(day)
    stats = compute_day_stats(entries)

    text = None
    if ai and cfg.get("ai_summary", {}).get("enabled", True):
        prompt = _build_ai_prompt(entries, day, stats)
        timeout_sec = cfg.get("ai_summary", {}).get("timeout_sec", 30)
        text = _call_headless_claude(prompt, timeout_sec)

    if text is None:
        text = template_summary(entries, day)

    ensure_dirs()
    out_path = SUMMARIES_DIR / f"{day.isoformat()}.md"
    out_path.write_text(text)
    return text
