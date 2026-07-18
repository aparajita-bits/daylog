"""Template-based standup generation: group yesterday/today entries by jira then category."""

from __future__ import annotations


from daylog.models import Entry


def _fmt_duration(minutes: int) -> str:
    if minutes >= 60:
        h, m = divmod(minutes, 60)
        return f"{h}h{m}m" if m else f"{h}h"
    return f"{minutes}m"


def _group_lines(entries: list[Entry]) -> list[str]:
    by_jira: dict[str, list[Entry]] = {}
    others: list[Entry] = []
    for e in entries:
        if e.jira:
            by_jira.setdefault(e.jira, []).append(e)
        else:
            others.append(e)

    lines = []
    for jira, group in sorted(by_jira.items()):
        total = sum(e.duration_min for e in group)
        titles = "; ".join(dict.fromkeys(e.title for e in group))
        lines.append(f"- {titles} ({jira}, {_fmt_duration(total)})")

    by_category: dict[str, list[Entry]] = {}
    for e in others:
        by_category.setdefault(e.category, []).append(e)

    for category, group in by_category.items():
        if category == "review" and len(group) > 1:
            lines.append(f"- Reviewed {len(group)} PRs")
            continue
        for e in group:
            lines.append(f"- {e.title} ({_fmt_duration(e.duration_min)})")

    return lines


def build_standup(yesterday_entries: list[Entry], today_entries: list[Entry]) -> str:
    parts = ["Yesterday:"]
    y_lines = _group_lines(yesterday_entries)
    parts.extend(y_lines if y_lines else ["- (nothing logged)"])
    parts.append("")
    parts.append("Today:")
    t_lines = _group_lines(today_entries)
    parts.extend(t_lines if t_lines else ["- (nothing logged yet)"])
    return "\n".join(parts)
