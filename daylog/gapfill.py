"""Timeline rendering + interactive gap-filling for `dl fill`."""

from __future__ import annotations

import subprocess
from datetime import date, datetime, time
from typing import Callable

from rich.console import Console

from daylog import store
from daylog.infer import parse_shorthand, infer_category
from daylog.models import Entry

console = Console()


def _parse_hhmm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def compute_gaps(
    entries: list[Entry],
    day: date,
    working_start: time,
    working_end: time,
    min_gap_min: int,
) -> list[tuple[datetime, datetime]]:
    tz = datetime.now().astimezone().tzinfo
    start_of_day = datetime.combine(day, working_start, tzinfo=tz)
    end_of_day = datetime.combine(day, working_end, tzinfo=tz)
    now = datetime.now().astimezone()
    cap_end = min(end_of_day, now) if day == now.date() else end_of_day
    if cap_end <= start_of_day:
        return []

    sorted_entries = sorted(entries, key=lambda e: e.ts)
    gaps = []
    cursor = start_of_day
    for e in sorted_entries:
        if e.ts > cursor:
            gaps.append((cursor, e.ts))
        cursor = max(cursor, e.end_ts)
    if cursor < cap_end:
        gaps.append((cursor, cap_end))

    return [(s, e) for s, e in gaps if (e - s).total_seconds() / 60 >= min_gap_min]


def capture_summary(entries: list[Entry], day: date, cfg: dict) -> dict:
    working_start = _parse_hhmm(cfg["working_hours"]["start"])
    working_end = _parse_hhmm(cfg["working_hours"]["end"])
    tz = datetime.now().astimezone().tzinfo
    start_of_day = datetime.combine(day, working_start, tzinfo=tz)
    end_of_day = datetime.combine(day, working_end, tzinfo=tz)
    now = datetime.now().astimezone()
    cap_end = min(end_of_day, now) if day == now.date() else end_of_day

    captured_min = sum(e.duration_min for e in entries)
    working_min = max(0, int((cap_end - start_of_day).total_seconds() // 60))
    unaccounted_min = max(0, working_min - captured_min)
    return {"captured_min": captured_min, "working_min": working_min, "unaccounted_min": unaccounted_min}


def render_timeline(entries: list[Entry], gaps: list[tuple[datetime, datetime]], day: date) -> None:
    rows: list[tuple[datetime, str]] = []
    for e in entries:
        marker = " (auto)" if e.source in ("claude-code", "calendar") else ""
        rows.append((e.ts, f"{e.ts:%H:%M}–{e.end_ts:%H:%M}  ▓ {e.category:<10} {e.title}{marker}"))
    for start, end in gaps:
        span = int((end - start).total_seconds() // 60)
        rows.append((start, f"{start:%H:%M}–{end:%H:%M}  ░ ── gap ──   ({span} min)"))

    console.print(f"[bold]daylog — {day.isoformat()}[/bold]")
    for _, line in sorted(rows, key=lambda r: r[0]):
        console.print(line)


def interactive_fill(
    day: date,
    cfg: dict,
    input_fn: Callable[[str], str] = input,
) -> list[Entry]:
    entries = store.read_entries(day)
    working_start = _parse_hhmm(cfg["working_hours"]["start"])
    working_end = _parse_hhmm(cfg["working_hours"]["end"])
    gaps = compute_gaps(entries, day, working_start, working_end, cfg["gapfill"]["min_gap_min"])

    render_timeline(entries, gaps, day)

    if not gaps:
        console.print("[dim]No gaps to fill.[/dim]")
        return []

    all_categories = cfg["categories"] + cfg["gapfill"]["excluded_categories"]
    new_entries = []
    for start, end in gaps:
        span = int((end - start).total_seconds() // 60)
        prompt = f"[Enter=skip] {start:%H:%M}–{end:%H:%M} was: "
        try:
            line = input_fn(prompt)
        except EOFError:
            break
        line = line.strip()
        if not line:
            continue
        parsed = parse_shorthand(line, all_categories, span)
        excluded = {c.lower() for c in cfg["gapfill"]["excluded_categories"]}
        title_lower = parsed["title"].strip().lower()
        if parsed["category"]:
            category = parsed["category"]
        elif title_lower in excluded:
            category = title_lower
        else:
            category = infer_category(line, cfg["categories"], default="other")
        entry = Entry(
            ts=start,
            duration_min=span,
            category=category,
            source="gapfill",
            title=parsed["title"],
            jira=parsed["jira"],
        )
        store.append_entry(entry, day=day)
        new_entries.append(entry)

    return new_entries


def _osascript_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def send_notification(title: str, message: str) -> None:
    try:
        script = f'display notification "{_osascript_escape(message)}" with title "{_osascript_escape(title)}"'
        subprocess.run(["osascript", "-e", script], check=False, timeout=5)
    except Exception:
        pass


def send_fill_notification(day: date, cfg: dict) -> None:
    entries = store.read_entries(day)
    summary = capture_summary(entries, day, cfg)
    captured_h = summary["captured_min"] / 60
    unaccounted_h = summary["unaccounted_min"] / 60
    send_notification(
        "daylog",
        f"{captured_h:.1f} hrs captured, ~{unaccounted_h:.1f} hrs unaccounted. Run `dl fill` to fill gaps.",
    )
