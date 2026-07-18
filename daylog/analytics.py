"""Weekly analytics: capture rate, category breakdown, top items, focus blocks, trends."""

from __future__ import annotations

from datetime import date, timedelta

from daylog import store
from daylog.models import Entry

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def week_bounds(reference: date, offset_weeks: int = 0) -> tuple[date, date]:
    monday = reference - timedelta(days=reference.weekday()) + timedelta(weeks=offset_weeks)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _working_minutes_per_day(cfg: dict) -> int:
    wh = cfg["working_hours"]
    sh, sm = map(int, wh["start"].split(":"))
    eh, em = map(int, wh["end"].split(":"))
    return (eh * 60 + em) - (sh * 60 + sm)


def _grouping_key(e: Entry) -> str:
    if e.jira:
        return e.jira
    # tags may include a unique `session:<id>` marker (Claude Code entries) — that
    # would defeat grouping since it's different for every session, so skip it.
    grouping_tags = [t for t in e.tags if not t.startswith("session:")]
    if grouping_tags:
        return grouping_tags[0]
    return e.title


def _longest_focus_block(day_entries: list[Entry]) -> int:
    """Longest run of back-to-back (<=5 min gap) coding entries, in minutes."""
    coding = sorted((e for e in day_entries if e.category == "coding"), key=lambda e: e.ts)
    if not coding:
        return 0
    longest = block = coding[0].duration_min
    block_end = coding[0].end_ts
    for e in coding[1:]:
        if (e.ts - block_end).total_seconds() <= 5 * 60:
            block += e.duration_min
        else:
            block = e.duration_min
        block_end = max(block_end, e.end_ts)
        longest = max(longest, block)
    return longest


def compute_stats(week_entries: dict[date, list[Entry]], cfg: dict) -> dict:
    all_entries = [e for entries in week_entries.values() for e in entries]
    total_captured = sum(e.duration_min for e in all_entries)

    working_days = sum(1 for d, entries in week_entries.items() if d.weekday() < 5)
    scheduled_min = working_days * _working_minutes_per_day(cfg)
    capture_rate = (total_captured / scheduled_min * 100) if scheduled_min else 0.0

    category_min: dict[str, int] = {}
    for e in all_entries:
        category_min[e.category] = category_min.get(e.category, 0) + e.duration_min

    grouped: dict[str, int] = {}
    for e in all_entries:
        key = _grouping_key(e)
        grouped[key] = grouped.get(key, 0) + e.duration_min
    top_items = sorted(grouped.items(), key=lambda kv: kv[1], reverse=True)[:5]

    focus_by_day = {d: _longest_focus_block(entries) for d, entries in week_entries.items()}

    meeting_by_weekday: dict[str, int] = {w: 0 for w in WEEKDAYS}
    for d, entries in week_entries.items():
        label = WEEKDAYS[d.weekday()]
        meeting_by_weekday[label] += sum(e.duration_min for e in entries if e.category == "meeting")

    backfilled = any(e.source.startswith("backfill-") for e in all_entries)

    return {
        "total_captured_min": total_captured,
        "scheduled_min": scheduled_min,
        "capture_rate": capture_rate,
        "category_min": category_min,
        "top_items": top_items,
        "focus_by_day": focus_by_day,
        "meeting_by_weekday": meeting_by_weekday,
        "backfilled": backfilled,
    }


def compare_stats(this_week: dict, prev_week: dict) -> dict:
    categories = set(this_week["category_min"]) | set(prev_week["category_min"])
    deltas = {
        c: this_week["category_min"].get(c, 0) - prev_week["category_min"].get(c, 0)
        for c in categories
    }
    return {
        "category_deltas": deltas,
        "total_delta_min": this_week["total_captured_min"] - prev_week["total_captured_min"],
        "capture_rate_delta": this_week["capture_rate"] - prev_week["capture_rate"],
    }


def load_week(monday: date) -> dict[date, list[Entry]]:
    sunday = monday + timedelta(days=6)
    return store.read_range(monday, sunday)


def stats_to_json_dict(stats: dict) -> dict:
    """JSON-safe transform of compute_stats' output: date keys -> isoformat
    strings, (key, minutes) tuples -> {"key": ..., "minutes": ...} dicts."""
    return {
        **stats,
        "top_items": [{"key": k, "minutes": m} for k, m in stats["top_items"]],
        "focus_by_day": {d.isoformat(): m for d, m in stats["focus_by_day"].items()},
    }
