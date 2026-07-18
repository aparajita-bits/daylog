"""JSONL read/write for the daily log files, one file per day: data/YYYY-MM-DD.jsonl."""

from __future__ import annotations

import json
import fcntl
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

from daylog.config import DATA_DIR, ensure_dirs
from daylog.models import Entry


def _path_for(day: date) -> Path:
    return DATA_DIR / f"{day.isoformat()}.jsonl"


def append_entry(entry: Entry, day: Optional[date] = None) -> Entry:
    ensure_dirs()
    day = day or entry.ts.date()
    path = _path_for(day)
    with open(path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(json.dumps(entry.to_dict()) + "\n")
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    return entry


def read_entries(day: date) -> list[Entry]:
    path = _path_for(day)
    if not path.exists():
        return []
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(Entry.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError):
                continue
    return sorted(entries, key=lambda e: e.ts)


def read_range(start: date, end: date) -> dict[date, list[Entry]]:
    result = {}
    d = start
    while d <= end:
        result[d] = read_entries(d)
        d += timedelta(days=1)
    return result


def write_entries(day: date, entries: Iterable[Entry]) -> None:
    ensure_dirs()
    path = _path_for(day)
    with open(path, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            for entry in sorted(entries, key=lambda e: e.ts):
                f.write(json.dumps(entry.to_dict()) + "\n")
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def update_entry(entry_id: str, day: date, **fields) -> Optional[Entry]:
    entries = read_entries(day)
    updated = None
    for e in entries:
        if e.id == entry_id:
            for k, v in fields.items():
                setattr(e, k, v)
            updated = e
            break
    if updated is not None:
        write_entries(day, entries)
    return updated


def find_entry(entry_id: str, day: Optional[date] = None) -> Optional[tuple[Entry, date]]:
    """Find an entry by id. Searches `day` if given, else the last 30 days."""
    days = [day] if day else [date.today() - timedelta(days=n) for n in range(30)]
    for d in days:
        for e in read_entries(d):
            if e.id == entry_id:
                return e, d
    return None


def suggested_duration_min(day: date, cfg: dict, now: Optional[datetime] = None) -> int:
    """Best-guess duration for a new manual entry: elapsed time since the end
    of the day's last entry, capped so a first log after a long gap (lunch,
    an uncaptured meeting, overnight) doesn't produce an absurd duration.
    Falls back to cfg['default_duration_min'] when there's no prior entry for
    the day, or when the elapsed time is non-positive (clock skew / a
    backdated entry)."""
    now = now or datetime.now().astimezone()
    entries = read_entries(day)
    if not entries:
        return cfg["default_duration_min"]
    last = entries[-1]
    elapsed_min = (now - last.end_ts).total_seconds() / 60
    if elapsed_min <= 0:
        return cfg["default_duration_min"]
    cap = cfg.get("default_duration_min_cap", 180)
    return min(round(elapsed_min), cap)


def has_event_uid(day: date, event_uid: str) -> bool:
    return any(e.event_uid == event_uid for e in read_entries(day))


def has_session_id(day: date, session_id: str) -> bool:
    return any(e.tags and f"session:{session_id}" in e.tags for e in read_entries(day))


def find_entry_by_session(day: date, session_id: str) -> Optional[Entry]:
    tag = f"session:{session_id}"
    for e in read_entries(day):
        if e.tags and tag in e.tags:
            return e
    return None
