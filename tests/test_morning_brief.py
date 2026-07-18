import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date, datetime


def _reload(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.morning_brief as morning_brief_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(morning_brief_module)
    return config_module, morning_brief_module


def test_disabled_by_default(tmp_path, monkeypatch):
    config_module, morning_brief_module = _reload(tmp_path, monkeypatch)

    result = morning_brief_module.run_morning_brief(config_module.DEFAULT_CONFIG)
    assert result == {"enabled": False}


def test_sends_via_notes_and_marks_idempotent(tmp_path, monkeypatch):
    config_module, morning_brief_module = _reload(tmp_path, monkeypatch)

    monkeypatch.setattr("daylog.summary.generate_summary", lambda day, cfg, ai: "yesterday's standup text")
    monkeypatch.setattr(morning_brief_module, "_write_note", lambda title, body: True)

    cfg = {**config_module.DEFAULT_CONFIG, "morning_brief": {**config_module.DEFAULT_CONFIG["morning_brief"], "enabled": True}}
    now = datetime.combine(date.today(), datetime.min.time()).astimezone().replace(hour=9)

    result = morning_brief_module.run_morning_brief(cfg, now=now)
    assert result == {"enabled": True, "delivery": "notes", "sent": True}

    # Second call the same day must no-op (idempotent), even if _write_note
    # would otherwise succeed again.
    second = morning_brief_module.run_morning_brief(cfg, now=now)
    assert second["sent"] is False
    assert second["reason"] == "already sent today"


def test_before_earliest_hour_does_not_send(tmp_path, monkeypatch):
    config_module, morning_brief_module = _reload(tmp_path, monkeypatch)

    write_calls = []
    monkeypatch.setattr("daylog.summary.generate_summary", lambda day, cfg, ai: "text")
    monkeypatch.setattr(morning_brief_module, "_write_note", lambda title, body: write_calls.append(1) or True)

    mb_cfg = {**config_module.DEFAULT_CONFIG["morning_brief"], "enabled": True, "earliest_hour": 6}
    cfg = {**config_module.DEFAULT_CONFIG, "morning_brief": mb_cfg}
    now = datetime.combine(date.today(), datetime.min.time()).astimezone().replace(hour=3)

    result = morning_brief_module.run_morning_brief(cfg, now=now)
    assert result["sent"] is False
    assert "earliest_hour" in result["reason"]
    assert write_calls == []


def test_failed_delivery_is_not_marked_sent_and_retries_next_poll(tmp_path, monkeypatch):
    config_module, morning_brief_module = _reload(tmp_path, monkeypatch)

    write_calls = []
    monkeypatch.setattr("daylog.summary.generate_summary", lambda day, cfg, ai: "text")
    monkeypatch.setattr(morning_brief_module, "_write_note", lambda title, body: write_calls.append(1) or False)

    cfg = {**config_module.DEFAULT_CONFIG, "morning_brief": {**config_module.DEFAULT_CONFIG["morning_brief"], "enabled": True}}
    now = datetime.combine(date.today(), datetime.min.time()).astimezone().replace(hour=9)

    first = morning_brief_module.run_morning_brief(cfg, now=now)
    assert first["sent"] is False

    second = morning_brief_module.run_morning_brief(cfg, now=now)
    assert second["sent"] is False
    assert second.get("reason") != "already sent today"  # must actually retry, not treat as done
    assert len(write_calls) == 2


def test_email_delivery_requires_recipient(tmp_path, monkeypatch):
    config_module, morning_brief_module = _reload(tmp_path, monkeypatch)

    monkeypatch.setattr("daylog.summary.generate_summary", lambda day, cfg, ai: "text")

    cfg = {
        **config_module.DEFAULT_CONFIG,
        "morning_brief": {**config_module.DEFAULT_CONFIG["morning_brief"], "enabled": True, "delivery": "email"},
    }
    now = datetime.combine(date.today(), datetime.min.time()).astimezone().replace(hour=9)

    result = morning_brief_module.run_morning_brief(cfg, now=now)
    assert result["sent"] is False
    assert result["reason"] == "no recipient configured"


def test_email_delivery_uses_headless_claude_when_recipient_set(tmp_path, monkeypatch):
    config_module, morning_brief_module = _reload(tmp_path, monkeypatch)

    monkeypatch.setattr("daylog.summary.generate_summary", lambda day, cfg, ai: "text")
    monkeypatch.setattr(morning_brief_module.shutil, "which", lambda name: "/usr/local/bin/claude")

    captured = {}

    class FakeResult:
        returncode = 0
        stdout = "ok"

    def fake_run(command, **kwargs):
        captured["command"] = command
        return FakeResult()

    monkeypatch.setattr(morning_brief_module.subprocess, "run", fake_run)

    cfg = {
        **config_module.DEFAULT_CONFIG,
        "morning_brief": {
            **config_module.DEFAULT_CONFIG["morning_brief"],
            "enabled": True,
            "delivery": "email",
            "recipient_email": "me@example.com",
        },
    }
    now = datetime.combine(date.today(), datetime.min.time()).astimezone().replace(hour=9)

    result = morning_brief_module.run_morning_brief(cfg, now=now)
    assert result["sent"] is True
    assert "me@example.com" in captured["command"][2]  # the prompt text
