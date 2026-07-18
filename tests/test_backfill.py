import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date, datetime, timedelta


def _write_transcript(
    path: Path,
    session_id: str,
    cwd: str,
    start: datetime,
    end: datetime,
    first_message: str = "do the thing",
    ai_title: str | None = None,
) -> None:
    """Writes a realistic transcript: messages every 3 minutes from start to end,
    so inter-message gaps stay well under IDLE_CUTOFF_MIN and the full span
    counts as active time (matching how real Claude Code sessions look).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [{"type": "mode", "sessionId": session_id}]
    if ai_title:
        lines.append({"type": "ai-title", "aiTitle": ai_title, "sessionId": session_id})
    ts = start
    role = "user"
    first = True
    while ts <= end:
        line = {
            "type": role,
            "sessionId": session_id,
            "timestamp": ts.astimezone().isoformat().replace("+00:00", "Z"),
            "message": {"role": role, "content": first_message if first else "..."},
        }
        if first:
            line["cwd"] = cwd
            first = False
        lines.append(line)
        role = "assistant" if role == "user" else "user"
        ts += timedelta(minutes=3)
    with open(path, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")


def test_walk_claude_sessions_skips_malformed_and_short(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path / "daylog-home"))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.backfill as backfill_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(backfill_module)

    projects_dir = tmp_path / "claude-projects"
    now = datetime.now().astimezone()

    # A real 15-minute session -> should be captured
    _write_transcript(
        projects_dir / "-fake-project" / "sess-good.jsonl",
        "sess-good",
        "/Users/fake/fake-project",
        now - timedelta(days=1, minutes=15),
        now - timedelta(days=1),
    )

    # A 2-minute session -> below threshold, should be skipped
    _write_transcript(
        projects_dir / "-fake-project" / "sess-short.jsonl",
        "sess-short",
        "/Users/fake/fake-project",
        now - timedelta(days=1, minutes=2),
        now - timedelta(days=1),
    )

    # A malformed file: no valid JSON at all -> should be skipped + logged
    malformed_path = projects_dir / "-fake-project" / "sess-malformed.jsonl"
    malformed_path.parent.mkdir(parents=True, exist_ok=True)
    malformed_path.write_text("not json at all\n{also not json\n")

    sessions = backfill_module.walk_claude_sessions(days=7, threshold_min=10, projects_dir=projects_dir)
    assert [s["session_id"] for s in sessions] == ["sess-good"]
    assert sessions[0]["project"] == "fake-project"
    assert round(sum(sessions[0]["day_minutes"].values())) == 15

    assert backfill_module.BACKFILL_ERROR_LOG.exists()
    log_text = backfill_module.BACKFILL_ERROR_LOG.read_text()
    assert "sess-malformed" in log_text


def test_backfill_claude_sessions_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path / "daylog-home"))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.backfill as backfill_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(backfill_module)

    projects_dir = tmp_path / "claude-projects"
    now = datetime.now().astimezone()
    _write_transcript(
        projects_dir / "-fake-project" / "sess-good.jsonl",
        "sess-good",
        "/Users/fake/fake-project",
        now - timedelta(days=1, minutes=20),
        now - timedelta(days=1),
    )

    cfg = config_module.DEFAULT_CONFIG
    first_run = backfill_module.backfill_claude_sessions(7, cfg, projects_dir=projects_dir)
    assert len(first_run) == 1
    # Regression: backfilled entries used to be bare "Claude Code: <project>"
    # with no detail, unlike the live hook's entries — should carry the same
    # first-prompt summary the live Stop hook attaches.
    assert first_run[0].title == "Claude Code: fake-project — do the thing"

    second_run = backfill_module.backfill_claude_sessions(7, cfg, projects_dir=projects_dir)
    assert second_run == []  # idempotent: session already logged


def test_backfill_prefers_ai_title_over_raw_first_message(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path / "daylog-home"))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.backfill as backfill_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(backfill_module)

    projects_dir = tmp_path / "claude-projects"
    now = datetime.now().astimezone()
    _write_transcript(
        projects_dir / "-fake-project" / "sess-with-title.jsonl",
        "sess-with-title",
        "/Users/fake/fake-project",
        now - timedelta(days=1, minutes=20),
        now - timedelta(days=1),
        first_message='{"code": "ERR001", "message": "raw pasted error blob"}',
        ai_title="Debug ERR001 API error",
    )

    cfg = config_module.DEFAULT_CONFIG
    entries = backfill_module.backfill_claude_sessions(7, cfg, projects_dir=projects_dir)
    assert len(entries) == 1
    assert entries[0].title == "Claude Code: fake-project — Debug ERR001 API error"


def test_backfill_collapses_whitespace_when_no_ai_title(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path / "daylog-home"))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.backfill as backfill_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(backfill_module)

    projects_dir = tmp_path / "claude-projects"
    now = datetime.now().astimezone()
    _write_transcript(
        projects_dir / "-fake-project" / "sess-multiline.jsonl",
        "sess-multiline",
        "/Users/fake/fake-project",
        now - timedelta(days=1, minutes=20),
        now - timedelta(days=1),
        first_message="line one\nline two\n\nline three",
    )

    cfg = config_module.DEFAULT_CONFIG
    entries = backfill_module.backfill_claude_sessions(7, cfg, projects_dir=projects_dir)
    assert len(entries) == 1
    assert entries[0].title == "Claude Code: fake-project — line one line two line three"


def test_backfill_ai_flag_summarizes_when_no_ai_title(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path / "daylog-home"))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.backfill as backfill_module
    import daylog.summary as summary_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(backfill_module)
    importlib.reload(summary_module)

    projects_dir = tmp_path / "claude-projects"
    now = datetime.now().astimezone()
    _write_transcript(
        projects_dir / "-fake-project" / "sess-no-title.jsonl",
        "sess-no-title",
        "/Users/fake/fake-project",
        now - timedelta(days=1, minutes=20),
        now - timedelta(days=1),
        first_message='{"code": "ERR001", "message": "raw pasted error blob"}',
    )

    monkeypatch.setattr(
        backfill_module,
        "build_session_summary",
        lambda first_prompt, ai_title, use_ai, timeout_sec=20: (
            "Debug ERR001 error" if use_ai else "raw fallback"
        ),
    )

    cfg = config_module.DEFAULT_CONFIG
    entries = backfill_module.backfill_claude_sessions(7, cfg, projects_dir=projects_dir, ai=True)
    assert entries[0].title == "Claude Code: fake-project — Debug ERR001 error"


def test_build_session_summary_falls_back_when_headless_claude_unavailable(monkeypatch):
    import daylog.backfill as backfill_module

    # Simulate `claude` not being on PATH — build_session_summary must not raise
    # and must fall back to the collapsed raw text.
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = backfill_module.build_session_summary(
        first_prompt="line one\nline two", ai_title=None, use_ai=True
    )
    assert result == "line one line two"


def test_import_jira_events_idempotent_and_needs_review(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path / "daylog-home"))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.backfill as backfill_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(backfill_module)

    events = [
        {
            "key": "AXON-9999",
            "summary": "Fixed the thing",
            "transitioned_at": (datetime.now().astimezone() - timedelta(days=1)).isoformat(),
        }
    ]

    first = backfill_module.import_jira_events(events)
    assert len(first) == 1
    assert first[0].needs_review is True
    assert first[0].duration_min == 60
    assert first[0].source == "backfill-jira"

    second = backfill_module.import_jira_events(events)
    assert second == []  # idempotent


def test_import_jira_events_tags_done_transitions(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path / "daylog-home"))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.backfill as backfill_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(backfill_module)

    now = datetime.now().astimezone() - timedelta(days=1)
    events = [
        {"key": "AXON-1", "action": "transitioned to Done", "transitioned_at": now.isoformat()},
        {"key": "AXON-2", "action": "moved to In Review", "transitioned_at": now.isoformat()},
        {"key": "AXON-3", "summary": "Investigated flaky test", "transitioned_at": now.isoformat()},
    ]

    entries = backfill_module.import_jira_events(events)
    by_key = {e.jira: e for e in entries}

    assert backfill_module.DONE_STATUS_TAG in by_key["AXON-1"].tags
    assert backfill_module.DONE_STATUS_TAG not in by_key["AXON-2"].tags
    assert backfill_module.DONE_STATUS_TAG not in by_key["AXON-3"].tags  # no action text at all


def test_import_outlook_events_routes_through_calendar_sync_day(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path / "daylog-home"))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.calendar_sync as calendar_sync_module
    import daylog.backfill as backfill_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(calendar_sync_module)
    importlib.reload(backfill_module)

    events = [
        {
            "uid": "outlook-evt-1",
            "title": "Design review",
            "start": datetime(2026, 7, 6, 14, 0).astimezone().isoformat(),
            "end": datetime(2026, 7, 6, 14, 30).astimezone().isoformat(),
            "all_day": False,
            "status": "accepted",
        }
    ]

    cfg = config_module.DEFAULT_CONFIG
    entries = backfill_module.import_outlook_events(events, cfg)

    assert len(entries) == 1
    assert entries[0].source == "outlook"
    assert entries[0].event_uid == "outlook-evt-1"
    assert entries[0].category == "meeting"

    # Idempotent, same as the eventkit backend's sync_day.
    second_run = backfill_module.import_outlook_events(events, cfg)
    assert second_run == []


def test_import_outlook_events_groups_by_start_date(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path / "daylog-home"))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.calendar_sync as calendar_sync_module
    import daylog.backfill as backfill_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(calendar_sync_module)
    importlib.reload(backfill_module)

    events = [
        {
            "uid": "outlook-evt-mon",
            "title": "Monday sync",
            "start": datetime(2026, 7, 6, 10, 0).astimezone().isoformat(),
            "end": datetime(2026, 7, 6, 10, 30).astimezone().isoformat(),
            "all_day": False,
            "status": "accepted",
        },
        {
            "uid": "outlook-evt-tue",
            "title": "Tuesday sync",
            "start": datetime(2026, 7, 7, 10, 0).astimezone().isoformat(),
            "end": datetime(2026, 7, 7, 10, 30).astimezone().isoformat(),
            "all_day": False,
            "status": "accepted",
        },
    ]

    cfg = config_module.DEFAULT_CONFIG
    entries = backfill_module.import_outlook_events(events, cfg)
    assert len(entries) == 2
    assert store_module.read_entries(date(2026, 7, 6))[0].event_uid == "outlook-evt-mon"
    assert store_module.read_entries(date(2026, 7, 7))[0].event_uid == "outlook-evt-tue"


def test_import_confluence_events_idempotent_and_needs_review(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path / "daylog-home"))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.backfill as backfill_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(backfill_module)

    events = [
        {
            "page_id": "123456",
            "title": "Payment retry design",
            "space": "ENG",
            "action": "edited",
            "timestamp": datetime.now().astimezone().isoformat(),
        }
    ]

    first = backfill_module.import_confluence_events(events)
    assert len(first) == 1
    assert first[0].needs_review is True
    assert first[0].source == "confluence"
    assert first[0].category == "discussion"
    assert first[0].duration_min == 25
    assert "Payment retry design" in first[0].title
    assert "ENG" in first[0].title

    second = backfill_module.import_confluence_events(events)
    assert second == []  # idempotent


def test_import_confluence_events_edited_and_commented_are_distinct(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path / "daylog-home"))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.backfill as backfill_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(backfill_module)

    now = datetime.now().astimezone().isoformat()
    events = [
        {"page_id": "1", "title": "Runbook", "action": "edited", "timestamp": now},
        {"page_id": "1", "title": "Runbook", "action": "commented", "timestamp": now},
    ]

    entries = backfill_module.import_confluence_events(events)
    assert len(entries) == 2
    assert {e.duration_min for e in entries} == {25, 15}
    assert any(e.title.startswith("Edited") for e in entries)
    assert any(e.title.startswith("Commented on") for e in entries)


def test_backfilled_week_gets_comparability_footnote(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path / "daylog-home"))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module

    importlib.reload(config_module)
    importlib.reload(store_module)

    from daylog.analytics import compute_stats, week_bounds, load_week
    from daylog.models import Entry

    today = date.today()
    monday, _ = week_bounds(today, 0)
    store_module.append_entry(
        Entry(
            ts=datetime.combine(monday, datetime.min.time()).astimezone(),
            duration_min=60,
            category="coding",
            source="backfill-jira",
            title="backfilled work",
            jira="AXON-1",
            needs_review=True,
        ),
        day=monday,
    )

    stats = compute_stats(load_week(monday), config_module.DEFAULT_CONFIG)
    assert stats["backfilled"] is True
