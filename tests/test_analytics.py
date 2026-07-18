import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from daylog.analytics import compute_stats, week_bounds, load_week
from daylog.config import DEFAULT_CONFIG
from make_fake_week import build_fake_week


def test_weekly_stats_match_hand_computation(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module

    importlib.reload(config_module)
    importlib.reload(store_module)

    from datetime import date, timedelta

    today = date.today()
    monday = today - timedelta(days=today.weekday())
    monday_dt = __import__("datetime").datetime.combine(monday, __import__("datetime").time())

    build_fake_week(monday_dt)

    week_entries = load_week(monday)
    stats = compute_stats(week_entries, DEFAULT_CONFIG)

    assert stats["total_captured_min"] == 900
    assert stats["category_min"]["coding"] == 540
    assert stats["category_min"]["meeting"] == 240
    assert stats["category_min"]["review"] == 30
    assert stats["category_min"]["firefighting"] == 90

    assert stats["scheduled_min"] == 5 * 540  # 5 working days * 9h
    assert round(stats["capture_rate"], 2) == round(900 / 2700 * 100, 2)

    top_keys = [k for k, _ in stats["top_items"]]
    assert top_keys[0] == "AXON-1"
    assert top_keys[1] == "AXON-2"

    assert stats["meeting_by_weekday"]["Mon"] == 60
    assert stats["meeting_by_weekday"]["Wed"] == 180
    assert stats["meeting_by_weekday"]["Tue"] == 0

    assert not stats["backfilled"]


def test_week_bounds():
    from datetime import date

    wed = date(2026, 7, 8)  # a Wednesday
    monday, sunday = week_bounds(wed, 0)
    assert monday.weekday() == 0
    assert sunday.weekday() == 6
    assert (sunday - monday).days == 6

    prev_monday, _ = week_bounds(wed, -1)
    assert (monday - prev_monday).days == 7
