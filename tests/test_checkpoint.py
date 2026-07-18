import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date


def test_run_checkpoint_disabled_via_config(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path))
    import importlib
    import daylog.config as config_module
    import daylog.checkpoint as checkpoint_module

    importlib.reload(config_module)
    importlib.reload(checkpoint_module)

    cfg = {**config_module.DEFAULT_CONFIG, "checkpoint": {"enabled": False}}
    result = checkpoint_module.run_checkpoint(date.today(), cfg)
    assert result == {"enabled": False}


def test_run_checkpoint_orchestrates_all_three_steps(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path))
    import importlib
    import daylog.config as config_module
    import daylog.checkpoint as checkpoint_module

    importlib.reload(config_module)
    importlib.reload(checkpoint_module)

    calls = []
    monkeypatch.setattr("daylog.calendar_sync.calendar_sync", lambda day, cfg: calls.append("calendar") or [1, 2])
    monkeypatch.setattr("daylog.github_sync.sync_prs", lambda day, cfg: calls.append("github") or [1])
    monkeypatch.setattr(checkpoint_module, "run_jira_checkpoint", lambda timeout_sec, skip_permissions: calls.append("jira") or True)
    monkeypatch.setattr("daylog.summary.generate_summary", lambda day, cfg, ai: calls.append("summary") or "ok")

    cfg = config_module.DEFAULT_CONFIG
    result = checkpoint_module.run_checkpoint(date.today(), cfg)

    assert calls == ["calendar", "github", "jira", "summary"]
    assert result == {"enabled": True, "calendar": 2, "github": 1, "jira_ran": True}


def test_run_checkpoint_runs_outlook_step_only_when_backend_is_outlook(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path))
    import importlib
    import daylog.config as config_module
    import daylog.checkpoint as checkpoint_module

    importlib.reload(config_module)
    importlib.reload(checkpoint_module)

    monkeypatch.setattr("daylog.calendar_sync.calendar_sync", lambda day, cfg: [])
    monkeypatch.setattr("daylog.github_sync.sync_prs", lambda day, cfg: [])
    monkeypatch.setattr(checkpoint_module, "run_jira_checkpoint", lambda timeout_sec, skip_permissions: True)
    monkeypatch.setattr("daylog.summary.generate_summary", lambda day, cfg, ai: "ok")

    outlook_calls = []
    monkeypatch.setattr(
        checkpoint_module,
        "run_outlook_checkpoint",
        lambda timeout_sec, skip_permissions: outlook_calls.append(1) or True,
    )

    cfg_eventkit = config_module.DEFAULT_CONFIG
    result = checkpoint_module.run_checkpoint(date.today(), cfg_eventkit)
    assert "outlook_ran" not in result
    assert outlook_calls == []

    cfg_outlook = {
        **config_module.DEFAULT_CONFIG,
        "calendar_sync": {**config_module.DEFAULT_CONFIG["calendar_sync"], "backend": "outlook"},
    }
    result = checkpoint_module.run_checkpoint(date.today(), cfg_outlook)
    assert result["outlook_ran"] is True
    assert outlook_calls == [1]


def test_run_jira_checkpoint_without_claude_on_path(monkeypatch):
    import daylog.checkpoint as checkpoint_module

    monkeypatch.setattr(checkpoint_module.shutil, "which", lambda name: None)
    assert checkpoint_module.run_jira_checkpoint(timeout_sec=5) is False


def test_run_jira_checkpoint_passes_skip_permissions_flag(monkeypatch):
    import daylog.checkpoint as checkpoint_module

    monkeypatch.setattr(checkpoint_module.shutil, "which", lambda name: "/usr/local/bin/claude")

    captured = {}

    class FakeResult:
        returncode = 0
        stdout = "ok"

    def fake_run(command, **kwargs):
        captured["command"] = command
        return FakeResult()

    monkeypatch.setattr(checkpoint_module.subprocess, "run", fake_run)

    checkpoint_module.run_jira_checkpoint(timeout_sec=5, skip_permissions=True)
    assert "--dangerously-skip-permissions" in captured["command"]

    checkpoint_module.run_jira_checkpoint(timeout_sec=5, skip_permissions=False)
    assert "--dangerously-skip-permissions" not in captured["command"]
