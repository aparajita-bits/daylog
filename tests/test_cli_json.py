import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date, datetime

from typer.testing import CliRunner


def test_day_json_output_matches_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.cli as cli_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(cli_module)

    from daylog.models import Entry

    today = date.today()
    store_module.append_entry(
        Entry(
            ts=datetime.combine(today, datetime.min.time()).astimezone().replace(hour=9),
            duration_min=60,
            category="coding",
            source="manual",
            title="fixed a bug",
            jira="AXON-1",
        ),
        day=today,
    )
    store_module.append_entry(
        Entry(
            ts=datetime.combine(today, datetime.min.time()).astimezone().replace(hour=11),
            duration_min=30,
            category="meeting",
            source="manual",
            title="standup",
        ),
        day=today,
    )

    runner = CliRunner()
    result = runner.invoke(cli_module.app, ["day", "--json"])
    assert result.exit_code == 0

    payload = json.loads(result.stdout)
    assert payload["date"] == today.isoformat()
    assert payload["total_captured_min"] == 90
    assert payload["category_min"] == {"coding": 60, "meeting": 30}
    assert len(payload["entries"]) == 2
    assert payload["entries"][0]["jira"] == "AXON-1"


def test_day_json_empty_day_is_valid_json(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.cli as cli_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(cli_module)

    runner = CliRunner()
    result = runner.invoke(cli_module.app, ["day", "--json", "--date", "2020-01-01"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload == {
        "date": "2020-01-01",
        "total_captured_min": 0,
        "category_min": {},
        "unaccounted_min": 540,  # default working_hours 09:00-18:00, nothing captured
        "gaps": [{"start": "09:00", "end": "18:00", "span_min": 540}],
        "entries": [],
    }


def test_quicklog_at_and_duration_backdate_a_gap_fill(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.cli as cli_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(cli_module)

    runner = CliRunner()
    result = runner.invoke(cli_module.app, ["quicklog", "filled a gap", "--at", "10:15", "-d", "25"])
    assert result.exit_code == 0

    entries = store_module.read_entries(date.today())
    assert len(entries) == 1
    assert entries[0].ts.strftime("%H:%M") == "10:15"
    assert entries[0].duration_min == 25
    assert entries[0].title == "filled a gap"


def test_quicklog_explicit_duration_in_text_overrides_the_gap_fill_default(tmp_path, monkeypatch):
    """Regression: -d is the gap-fill *default* (what the widget passes as
    the gap's full span), not a hard override -- if the user actually types
    a duration ("wrote docs 30m"), that must win, not silently get replaced
    by the gap span. Previously `duration_min=duration or parsed[...]`
    always picked `duration` whenever `-d` was passed, discarding whatever
    the user typed."""
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.cli as cli_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(cli_module)

    runner = CliRunner()
    # -d 120 simulates the widget passing a 2-hour gap's span; the user's
    # own "30m" in the text must win over that default.
    result = runner.invoke(cli_module.app, ["quicklog", "wrote docs 30m", "--at", "09:00", "-d", "120"])
    assert result.exit_code == 0

    entries = store_module.read_entries(date.today())
    assert len(entries) == 1
    assert entries[0].duration_min == 30
    assert entries[0].title == "wrote docs"


def test_week_json_output_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.cli as cli_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(cli_module)

    from daylog.models import Entry

    today = date.today()
    store_module.append_entry(
        Entry(
            ts=datetime.combine(today, datetime.min.time()).astimezone().replace(hour=9),
            duration_min=60,
            category="coding",
            source="manual",
            title="fixed a bug",
            jira="AXON-1",
        ),
        day=today,
    )

    runner = CliRunner()
    result = runner.invoke(cli_module.app, ["week", "--json"])
    assert result.exit_code == 0

    payload = json.loads(result.stdout)
    assert payload["total_captured_min"] == 60
    assert payload["category_min"] == {"coding": 60}
    assert payload["top_items"] == [{"key": "AXON-1", "minutes": 60}]
    assert all(isinstance(k, str) for k in payload["focus_by_day"])
    assert "week_start" in payload and "week_end" in payload


def test_review_json_without_ai_flag_reports_not_requested(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.cli as cli_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(cli_module)

    runner = CliRunner()
    result = runner.invoke(cli_module.app, ["review", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["insights"] is None
    assert "error" in payload


def test_review_json_with_ai_falls_back_gracefully_without_claude_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path))
    monkeypatch.setattr("shutil.which", lambda name: None)  # simulate no `claude` CLI on PATH
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.summary as summary_module
    import daylog.review as review_module
    import daylog.cli as cli_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(summary_module)
    importlib.reload(review_module)
    importlib.reload(cli_module)

    runner = CliRunner()
    result = runner.invoke(cli_module.app, ["review", "--json", "--ai"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["insights"] is None
    assert "error" in payload
