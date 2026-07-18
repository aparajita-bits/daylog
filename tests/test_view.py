import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date, datetime


def _reload(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.view as view_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(view_module)
    return config_module, store_module, view_module


def test_md_lite_bold_header_becomes_h3(tmp_path, monkeypatch):
    _, _, view_module = _reload(tmp_path, monkeypatch)

    html = view_module._md_lite_to_html("**Jira**\n- Fixed AXON-1234 (AXON-1234)")
    assert "<h3>Jira</h3>" in html
    assert "<ul>" in html and "<li>Fixed AXON-1234 (AXON-1234)</li>" in html


def test_md_lite_escapes_html_in_content(tmp_path, monkeypatch):
    _, _, view_module = _reload(tmp_path, monkeypatch)

    html = view_module._md_lite_to_html("- Discussed <script>alert(1)</script> with Priya")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_md_lite_inline_bold_and_code(tmp_path, monkeypatch):
    _, _, view_module = _reload(tmp_path, monkeypatch)

    html = view_module._md_lite_to_html("Ran `pytest` and **all tests passed**.")
    assert "<code>pytest</code>" in html
    assert "<strong>all tests passed</strong>" in html


def test_md_lite_empty_text(tmp_path, monkeypatch):
    _, _, view_module = _reload(tmp_path, monkeypatch)

    assert "nothing to show" in view_module._md_lite_to_html("")
    assert "nothing to show" in view_module._md_lite_to_html(None)


def test_stats_bars_html_scales_relative_to_max(tmp_path, monkeypatch):
    _, _, view_module = _reload(tmp_path, monkeypatch)

    html = view_module._stats_bars_html({"coding": 60, "meeting": 30})
    assert "width:100%" in html
    assert "width:50%" in html
    assert "1h" in html
    assert "30m" in html


def test_top_items_html_scales_relative_to_max(tmp_path, monkeypatch):
    _, _, view_module = _reload(tmp_path, monkeypatch)

    html = view_module._top_items_html([("AXON-1", 120), ("AXON-2", 60)])
    assert "AXON-1" in html and "AXON-2" in html
    assert "width:100%" in html
    assert "width:50%" in html
    assert "2h" in html


def test_top_items_html_empty(tmp_path, monkeypatch):
    _, _, view_module = _reload(tmp_path, monkeypatch)

    assert "nothing logged" in view_module._top_items_html([])


def test_weekday_bars_html_uses_ordered_days_for_meeting_load(tmp_path, monkeypatch):
    _, _, view_module = _reload(tmp_path, monkeypatch)
    from daylog.analytics import WEEKDAYS

    by_weekday = {"Mon": 30, "Tue": 0, "Wed": 60, "Thu": 0, "Fri": 0, "Sat": 0, "Sun": 0}
    html = view_module._weekday_bars_html(by_weekday, "#fca5a5", ordered_days=WEEKDAYS)

    # Monday's row must come before Wednesday's, matching WEEKDAYS order,
    # not alphabetical (which would put Fri/Mon/Sat/Sun/Thu/Tue/Wed first).
    assert html.index("Mon") < html.index("Wed")
    assert "30m" in html
    assert "1h" in html


def test_weekday_bars_html_focus_by_day_uses_date_keys(tmp_path, monkeypatch):
    _, _, view_module = _reload(tmp_path, monkeypatch)

    focus_by_day = {date(2026, 7, 13): 90, date(2026, 7, 14): 0}
    html = view_module._weekday_bars_html(focus_by_day, "#7dd3fc")
    assert "Mon 07-13" in html
    assert "1h30m" in html


def test_weekday_bars_html_empty(tmp_path, monkeypatch):
    _, _, view_module = _reload(tmp_path, monkeypatch)

    assert "nothing logged" in view_module._weekday_bars_html({}, "#7dd3fc")
    assert "nothing logged" in view_module._weekday_bars_html({"Mon": 0, "Tue": 0}, "#7dd3fc")


def test_daily_breakdown_html_shows_per_day_categories(tmp_path, monkeypatch):
    _, store_module, view_module = _reload(tmp_path, monkeypatch)
    from daylog.models import Entry

    monday = date(2026, 7, 13)
    tuesday = date(2026, 7, 14)
    monday_ts = datetime.combine(monday, datetime.min.time()).astimezone()
    tuesday_ts = datetime.combine(tuesday, datetime.min.time()).astimezone()
    week_entries = {
        monday: [
            Entry(ts=monday_ts, duration_min=60, category="coding", source="manual", title="a"),
        ],
        tuesday: [
            Entry(ts=tuesday_ts, duration_min=30, category="meeting", source="manual", title="b"),
        ],
        date(2026, 7, 15): [],
    }

    html = view_module._daily_breakdown_html(week_entries)
    assert "day-seg" in html
    assert "coding: 1h" in html
    assert "meeting: 30m" in html
    assert "—" in html  # the empty day shows a dash, not a zero-width bar


def test_daily_breakdown_html_empty_week(tmp_path, monkeypatch):
    _, _, view_module = _reload(tmp_path, monkeypatch)

    html = view_module._daily_breakdown_html({date(2026, 7, 13): []})
    assert "nothing logged" in html


def test_jira_completion_html_splits_done_vs_open(tmp_path, monkeypatch):
    _, _, view_module = _reload(tmp_path, monkeypatch)
    from daylog.backfill import DONE_STATUS_TAG
    from daylog.models import Entry

    day = date(2026, 7, 13)
    ts = datetime.combine(day, datetime.min.time()).astimezone()
    week_entries = {
        day: [
            Entry(ts=ts, duration_min=60, category="coding", source="backfill-jira", title="a", jira="AXON-1", tags=[DONE_STATUS_TAG]),
            Entry(ts=ts, duration_min=45, category="coding", source="backfill-jira", title="b", jira="AXON-2", tags=[]),
        ]
    }

    html = view_module._jira_completion_html(week_entries)
    assert "Closed this week" in html
    assert "AXON-1" in html
    assert "Touched, still open" in html
    assert "AXON-2" in html


def test_jira_completion_html_no_jira_entries(tmp_path, monkeypatch):
    _, _, view_module = _reload(tmp_path, monkeypatch)

    html = view_module._jira_completion_html({date(2026, 7, 13): []})
    assert "no Jira-linked entries" in html


def test_run_view_day_writes_html_without_opening_browser(tmp_path, monkeypatch):
    config_module, store_module, view_module = _reload(tmp_path, monkeypatch)
    from daylog.models import Entry

    today = date.today()
    store_module.append_entry(
        Entry(
            ts=datetime.combine(today, datetime.min.time()).astimezone().replace(hour=9),
            duration_min=45,
            category="coding",
            source="manual",
            title="did stuff",
            jira="AXON-1",
        ),
        day=today,
    )

    monkeypatch.setattr("daylog.summary._call_headless_claude", lambda prompt, timeout_sec: None)
    opened = []
    monkeypatch.setattr(view_module.webbrowser, "open", lambda uri: opened.append(uri))

    path = view_module.run_view(config_module.DEFAULT_CONFIG, week=False, open_browser=False)
    assert path.exists()
    content = path.read_text()
    assert "coding" in content
    assert "AXON-1" in content
    assert opened == []  # open_browser=False must not call webbrowser.open


def test_run_view_opens_browser_when_requested(tmp_path, monkeypatch):
    config_module, store_module, view_module = _reload(tmp_path, monkeypatch)

    monkeypatch.setattr("daylog.summary._call_headless_claude", lambda prompt, timeout_sec: None)
    opened = []
    monkeypatch.setattr(view_module.webbrowser, "open", lambda uri: opened.append(uri))

    view_module.run_view(config_module.DEFAULT_CONFIG, week=False, open_browser=True)
    assert len(opened) == 1
    assert opened[0].startswith("file://")


def test_run_view_week(tmp_path, monkeypatch):
    config_module, store_module, view_module = _reload(tmp_path, monkeypatch)

    monkeypatch.setattr(view_module.webbrowser, "open", lambda uri: None)

    path = view_module.run_view(config_module.DEFAULT_CONFIG, week=True, open_browser=False)
    content = path.read_text()
    assert path.exists()
    assert "Week of" in content
    assert "Where your time went" in content
    assert "Meeting load by weekday" in content
    assert "Longest focus block per day" in content
    # The week view deliberately has no AI Insights section (the
    # pattern-spotting prose wasn't useful) -- unlike the day view, which
    # keeps it (reuses the standup prompt, genuinely readable content).
    assert "Insights" not in content


def test_run_view_week_does_not_call_headless_claude(tmp_path, monkeypatch):
    """Regression: an earlier version of run_view(week=True) called
    generate_weekly_insights (a real headless `claude -p` subprocess) even
    though the result is no longer rendered -- wasteful and slow. Fails
    loudly if that call comes back."""
    config_module, store_module, view_module = _reload(tmp_path, monkeypatch)

    def _boom(*args, **kwargs):
        raise AssertionError("run_view(week=True) must not call the headless claude path")

    monkeypatch.setattr("daylog.review._call_headless_claude", _boom)
    monkeypatch.setattr(view_module.webbrowser, "open", lambda uri: None)

    view_module.run_view(config_module.DEFAULT_CONFIG, week=True, open_browser=False)
