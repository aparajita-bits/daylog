import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date, datetime

from daylog.config import DEFAULT_CONFIG
from daylog.models import Entry


def _iso(day: date, hour: int, minute: int = 0) -> str:
    return datetime(day.year, day.month, day.day, hour, minute).astimezone().isoformat()


def test_sync_day_skip_rules_and_dedup_and_idempotency(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.calendar_sync as calendar_sync_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(calendar_sync_module)
    from daylog.calendar_sync import sync_day as sync_day_reloaded

    day = date(2026, 7, 6)  # a Monday
    now = datetime(2026, 7, 6, 18, 0).astimezone()

    # A pre-existing manual entry logged by the user, 13:00-13:30
    manual_entry = Entry(
        ts=datetime(2026, 7, 6, 13, 0).astimezone(),
        duration_min=30,
        category="meeting",
        source="manual",
        title="Design sync with Priya",
    )
    store_module.append_entry(manual_entry, day=day)

    raw_events = [
        {  # declined -> skip
            "uid": "evt-declined",
            "title": "Skipped standup",
            "start": _iso(day, 9, 0),
            "end": _iso(day, 9, 30),
            "all_day": False,
            "status": "declined",
        },
        {  # all-day -> skip
            "uid": "evt-allday",
            "title": "Company holiday",
            "start": _iso(day, 0, 0),
            "end": _iso(day, 23, 59),
            "all_day": True,
            "status": "confirmed",
        },
        {  # overlaps the manual entry -> absorbed, not added
            "uid": "evt-overlap",
            "title": "Design sync",
            "start": _iso(day, 13, 5),
            "end": _iso(day, 13, 35),
            "all_day": False,
            "status": "confirmed",
        },
        {  # genuinely new, non-overlapping -> should be added
            "uid": "evt-new",
            "title": "1:1 with manager",
            "start": _iso(day, 15, 0),
            "end": _iso(day, 15, 30),
            "all_day": False,
            "status": "confirmed",
        },
        {  # too short -> skip
            "uid": "evt-short",
            "title": "Quick huddle",
            "start": _iso(day, 16, 0),
            "end": _iso(day, 16, 5),
            "all_day": False,
            "status": "confirmed",
        },
    ]

    added = sync_day_reloaded(day, raw_events, DEFAULT_CONFIG, now=now)
    assert [e.event_uid for e in added] == ["evt-new"]

    all_entries = store_module.read_entries(day)
    # manual entry + the one genuinely-new calendar entry = 2 total
    assert len(all_entries) == 2
    sources = sorted(e.source for e in all_entries)
    assert sources == ["calendar", "manual"]

    # Re-running with identical raw events must add nothing new (idempotent)
    added_again = sync_day_reloaded(day, raw_events, DEFAULT_CONFIG, now=now)
    assert added_again == []
    assert len(store_module.read_entries(day)) == 2


def test_calendar_sync_skips_eventkit_fetch_for_non_eventkit_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.calendar_sync as calendar_sync_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(calendar_sync_module)

    called = []
    monkeypatch.setattr(
        calendar_sync_module, "fetch_events_eventkit", lambda day: called.append(1) or []
    )

    cfg = {**config_module.DEFAULT_CONFIG, "calendar_sync": {**config_module.DEFAULT_CONFIG["calendar_sync"], "backend": "outlook"}}
    result = calendar_sync_module.calendar_sync(date(2026, 7, 6), cfg)
    assert result == []
    assert called == []  # the JXA/eventkit fetch must never run for a non-eventkit backend


def test_calendar_sync_still_uses_eventkit_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.calendar_sync as calendar_sync_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(calendar_sync_module)

    called = []
    monkeypatch.setattr(
        calendar_sync_module,
        "fetch_events_eventkit",
        lambda day, timeout_sec=120: called.append(1) or [],
    )

    calendar_sync_module.calendar_sync(date(2026, 7, 6), config_module.DEFAULT_CONFIG)
    assert called == [1]
