import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _reload_store(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    return store_module


def test_no_prior_entry_falls_back_to_default(tmp_path, monkeypatch):
    from datetime import date

    store = _reload_store(tmp_path, monkeypatch)
    cfg = {"default_duration_min": 30, "default_duration_min_cap": 180}

    assert store.suggested_duration_min(date.today(), cfg) == 30


def test_elapsed_time_since_last_entry_is_used(tmp_path, monkeypatch):
    from datetime import date, datetime, timedelta

    store = _reload_store(tmp_path, monkeypatch)
    from daylog.models import Entry

    cfg = {"default_duration_min": 30, "default_duration_min_cap": 180}
    today = date.today()
    start = datetime.combine(today, datetime.min.time()).astimezone().replace(hour=9)

    entry = Entry(ts=start, duration_min=25, category="coding", source="manual", title="did stuff")
    store.append_entry(entry, day=today)

    now = entry.end_ts + timedelta(minutes=42)
    assert store.suggested_duration_min(today, cfg, now=now) == 42


def test_elapsed_time_beyond_cap_is_capped(tmp_path, monkeypatch):
    from datetime import date, datetime, timedelta

    store = _reload_store(tmp_path, monkeypatch)
    from daylog.models import Entry

    cfg = {"default_duration_min": 30, "default_duration_min_cap": 180}
    today = date.today()
    start = datetime.combine(today, datetime.min.time()).astimezone().replace(hour=9)

    entry = Entry(ts=start, duration_min=25, category="coding", source="manual", title="did stuff")
    store.append_entry(entry, day=today)

    now = entry.end_ts + timedelta(hours=5)  # way past the 180-min cap
    assert store.suggested_duration_min(today, cfg, now=now) == 180


def test_nonpositive_elapsed_falls_back_to_default(tmp_path, monkeypatch):
    from datetime import date, datetime, timedelta

    store = _reload_store(tmp_path, monkeypatch)
    from daylog.models import Entry

    cfg = {"default_duration_min": 30, "default_duration_min_cap": 180}
    today = date.today()
    start = datetime.combine(today, datetime.min.time()).astimezone().replace(hour=9)

    entry = Entry(ts=start, duration_min=60, category="coding", source="manual", title="did stuff")
    store.append_entry(entry, day=today)

    # "now" is before the entry even ends (e.g. a backdated entry) — must not
    # return a negative/zero duration.
    now = entry.end_ts - timedelta(minutes=5)
    assert store.suggested_duration_min(today, cfg, now=now) == 30
