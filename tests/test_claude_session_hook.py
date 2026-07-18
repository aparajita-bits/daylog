import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _reload_hook(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import hooks.claude_session as hook_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(hook_module)
    return hook_module


def test_fresh_session_start_creates_empty_state(tmp_path, monkeypatch):
    hook = _reload_hook(tmp_path, monkeypatch)

    hook.handle_session_start({"session_id": "sess-1", "cwd": "/tmp/proj"})

    state_path = hook.STATE_DIR / "sess-1.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text())
    assert state["session_id"] == "sess-1"
    assert state["day_minutes"] == {}
    assert state["entry_ids"] == {}


def test_resumed_session_start_preserves_accumulated_state(tmp_path, monkeypatch):
    hook = _reload_hook(tmp_path, monkeypatch)

    hook.handle_session_start({"session_id": "sess-2", "cwd": "/tmp/proj"})
    state_path = hook.STATE_DIR / "sess-2.json"
    state = json.loads(state_path.read_text())

    # Simulate work already flushed for this session: a real entry exists and
    # is tracked in day_minutes/entry_ids.
    state["day_minutes"] = {"2026-07-18": 45.0}
    state["day_start"] = {"2026-07-18": "2026-07-18T09:00:00+00:00"}
    state["entry_ids"] = {"2026-07-18": "abc12345"}
    old_segment_start = state["segment_start"]
    state_path.write_text(json.dumps(state))

    # Claude Code fires SessionStart again on --resume with the same session_id.
    hook.handle_session_start({"session_id": "sess-2", "cwd": "/tmp/proj"})

    new_state = json.loads(state_path.read_text())
    assert new_state["day_minutes"] == {"2026-07-18": 45.0}
    assert new_state["entry_ids"] == {"2026-07-18": "abc12345"}
    # Only the in-progress segment clock should have moved.
    assert new_state["segment_start"] != old_segment_start


def test_corrupt_state_file_falls_back_to_fresh_state(tmp_path, monkeypatch):
    hook = _reload_hook(tmp_path, monkeypatch)

    hook.STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path = hook.STATE_DIR / "sess-3.json"
    state_path.write_text("not valid json {{{")

    hook.handle_session_start({"session_id": "sess-3", "cwd": "/tmp/proj"})

    state = json.loads(state_path.read_text())
    assert state["session_id"] == "sess-3"
    assert state["day_minutes"] == {}
    assert state["entry_ids"] == {}
