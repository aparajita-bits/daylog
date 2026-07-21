"""Calendar sweep: pull a day's events from macOS Calendar, dedup against manual
entries, log the rest as `category: meeting, source: calendar`.

Once-daily sweep by design, not continuous polling — see Component 5 in the
build plan for the rationale (no persistent daemon in v1).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from daylog import store
from daylog.config import DATA_DIR, STATE_DIR, ensure_dirs
from daylog.models import Entry

JXA_SCRIPT = Path(__file__).resolve().parent / "scripts" / "fetch_calendar_events.jxa"
_LAZY_MARKER_NAME = "calendar-sync-last-run.json"


def _absorbed_path(day: date) -> Path:
    return DATA_DIR / f"{day.isoformat()}.absorbed.json"


def _load_absorbed(day: date) -> set[str]:
    path = _absorbed_path(day)
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text()))
    except (json.JSONDecodeError, OSError):
        return set()


def _save_absorbed(day: date, uids: set[str]) -> None:
    ensure_dirs()
    _absorbed_path(day).write_text(json.dumps(sorted(uids)))


def fetch_events_eventkit(day: date, timeout_sec: int = 120) -> list[dict]:
    """Best-effort: query macOS Calendar.app via JXA. Returns [] on any failure
    (no Calendar access, not on macOS, permission denied, timeout, etc) rather
    than raising — calendar sync is optional and must never block `dl fill`.

    `timeout_sec` defaults generously: Calendar.app's `.whose()` date-range
    query is a linear scan, not indexed, and has been observed taking well
    over 30s on calendars with many (recurring) events -- a short timeout
    here just means every sync silently finds nothing.
    """
    if not shutil.which("osascript") or not JXA_SCRIPT.exists():
        return []
    try:
        result = subprocess.run(
            ["osascript", "-l", "JavaScript", str(JXA_SCRIPT), day.isoformat()],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def _is_declined(raw: dict) -> bool:
    status = (raw.get("status") or "").lower()
    return status in ("canceled", "cancelled", "declined")


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime, tolerance_min: int) -> bool:
    tol = timedelta(minutes=tolerance_min)
    return a_start - tol < b_end and b_start - tol < a_end


def sync_day(
    day: date,
    raw_events: list[dict],
    cfg: dict,
    now: Optional[datetime] = None,
    source_label: str = "calendar",
) -> list[Entry]:
    """Pure business logic: apply skip rules + dedup + idempotency to raw events
    for `day`, append any new calendar entries, and return the ones just added.

    `source_label` lets backfill.py reuse this for `source: backfill-calendar`
    without duplicating the skip/dedup logic.
    """
    cal_cfg = cfg["calendar_sync"]
    now = now or datetime.now().astimezone()
    existing_entries = store.read_entries(day)
    manual_entries = [e for e in existing_entries if not e.event_uid]
    already_synced_uids = {e.event_uid for e in existing_entries if e.event_uid}
    absorbed = _load_absorbed(day)

    ignore_titles = [t.lower() for t in cal_cfg["ignore_titles"]]
    new_entries = []

    for raw in raw_events:
        uid = raw.get("uid")
        if not uid or uid in already_synced_uids or uid in absorbed:
            continue

        try:
            start = datetime.fromisoformat(raw["start"])
            end = datetime.fromisoformat(raw["end"])
        except (KeyError, ValueError):
            continue

        if cal_cfg["skip_declined"] and _is_declined(raw):
            continue
        if cal_cfg["skip_all_day"] and raw.get("all_day"):
            continue
        if start > now:
            continue
        title = raw.get("title") or "(untitled)"
        if any(ignored in title.lower() for ignored in ignore_titles):
            continue
        duration_min = max(0, int((end - start).total_seconds() // 60))
        if duration_min < cal_cfg["min_duration_min"]:
            continue

        overlaps_manual = any(
            _overlaps(start, end, m.ts, m.end_ts, cal_cfg["dedup_tolerance_min"]) for m in manual_entries
        )
        if overlaps_manual:
            absorbed.add(uid)  # keep manual entry's richer context; never re-add this event
            continue

        entry = Entry(
            ts=start,
            duration_min=duration_min,
            category="meeting",
            source=source_label,
            title=title,
            event_uid=uid,
        )
        store.append_entry(entry, day=day)
        new_entries.append(entry)

    _save_absorbed(day, absorbed)
    return new_entries


def calendar_sync(day: date, cfg: dict) -> list[Entry]:
    if not cfg["calendar_sync"]["enabled"]:
        return []
    if cfg["calendar_sync"].get("backend", "eventkit") != "eventkit":
        # Non-eventkit backends (e.g. "outlook") have no synchronous fetch --
        # they sync via their own headless-MCP checkpoint step (see
        # checkpoint.py::run_outlook_checkpoint) into `dl import-events`
        # instead, which lands here through sync_day() the same way.
        return []
    raw_events = fetch_events_eventkit(day, timeout_sec=cfg["calendar_sync"].get("eventkit_timeout_sec", 120))
    return sync_day(day, raw_events, cfg)


def calendar_sync_range(
    start: date, end: date, cfg: dict, source_label: str = "calendar"
) -> dict[date, list[Entry]]:
    result = {}
    d = start
    while d <= end:
        if not cfg["calendar_sync"]["enabled"] or cfg["calendar_sync"].get("backend", "eventkit") != "eventkit":
            result[d] = []
        else:
            raw_events = fetch_events_eventkit(d, timeout_sec=cfg["calendar_sync"].get("eventkit_timeout_sec", 120))
            result[d] = sync_day(d, raw_events, cfg, source_label=source_label)
        d += timedelta(days=1)
    return result


def _lazy_marker_path() -> Path:
    return STATE_DIR / _LAZY_MARKER_NAME


def lazy_sync_if_needed(day: date, cfg: dict) -> bool:
    """`dl fill` calls this first. If the calendar part of today's scheduled
    17:45 checkpoint hasn't run yet (laptop asleep, or fill triggered early),
    run a quick sync now so fill only shows genuine unknowns. Only covers
    calendar — the checkpoint's GitHub/Jira parts have no lazy-fallback
    equivalent. Returns True if a sync ran.
    """
    if not cfg["calendar_sync"]["enabled"]:
        return False
    ensure_dirs()
    marker = _lazy_marker_path()
    data = {}
    if marker.exists():
        try:
            data = json.loads(marker.read_text())
        except (json.JSONDecodeError, OSError):
            data = {}

    if data.get(day.isoformat()):
        return False  # already synced today, scheduled run (or an earlier lazy sync) covered it

    calendar_sync(day, cfg)
    data[day.isoformat()] = datetime.now().astimezone().isoformat()
    marker.write_text(json.dumps(data))
    return True
